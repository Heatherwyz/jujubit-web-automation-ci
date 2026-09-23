#!/usr/bin/env python3
"""打开独立可见浏览器登录 JuJuBit，导出 Playwright storage-state。

Shopify Customer Accounts 的会话 Cookie 是 HttpOnly：页面里的 document.cookie、
Chrome DevTools 的普通 Cookie 列表、内置窗口的脚本都读不到。必须用 Playwright
自己的浏览器完成一次登录，再调用 storage_state()。

用法：
    .venv/bin/python scripts/export_storage_state.py

登录成功的判定是打开 /account 后地址栏不再是 Shopify 登录页。
会员页的 Current Plan 不够：未登录时 Basic 也会显示 Current Plan。

登录完成后脚本会写入 artifacts/auth/storage-state.json，然后优雅关闭
浏览器。不要强杀窗口，否则 cookie 来不及落盘。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "auth" / "storage-state.json"
PROFILE_DIR = ROOT / "artifacts" / "auth" / "chrome-profile"
ACCOUNT_URL = "https://jujubit.ai/account"
PAYWALL_URL = "https://jujubit.ai/pages/vip-program?entry_page=header"
# 必须走店面侧入口：/account/login 用 client_id 4a068d2f，回调到
# shopify.com/.../account/callback，只给 Shopify 托管账户页种会话，
# jujubit.ai 店面仍是未登录（会员页显示 "Log in to view your plan"）。
# /customer_authentication/login 用 client_id 13cb19b1，回调到
# jujubit.ai/customer_authentication/callback，才会给店面种会员会话。
STOREFRONT_LOGIN_URL = "https://jujubit.ai/customer_authentication/login"
# 验证码要人去邮箱里取，10 分钟不够：真实企业邮箱可能延迟几分钟才到。
WAIT_SECONDS = 1_200


def _cookie_summary(payload: dict) -> str:
    cookies = payload.get("cookies") or []
    names = sorted({str(cookie.get("name") or "") for cookie in cookies if cookie.get("name")})
    domains = sorted({str(cookie.get("domain") or "") for cookie in cookies if cookie.get("domain")})
    # 新版 Shopify Customer Accounts 用 _shopify_essential 承载会话，不是旧版
    # legacy 账户的 _secure_customer_sig；按旧名字找会误判成"没有登录凭据"。
    auth_names = [
        name
        for name in names
        if any(
            token in name.lower()
            for token in ("essential", "customer", "session", "secure")
        )
    ]
    return (
        f"cookies={len(cookies)} origins={len(payload.get('origins') or [])} "
        f"domains={','.join(domains) or '(none)'} "
        f"auth_like={','.join(auth_names) or '(none)'}"
    )


def is_logged_in_url(url: str) -> bool:
    """离开 Shopify 登录/验证码页就算这一跳走完了。

    这只是 URL 层面的粗筛，不等于店面已登录：真正的判定是会员页 overview
    不再显示 "Log in to view your plan"（见 storefront_signed_in）。
    """
    lowered = (url or "").lower()
    if "/login" in lowered or "authentication/" in lowered:
        return False
    if "jujubit.ai/account" in lowered:
        return True
    if "jujubit.ai/pages/vip-program" in lowered:
        return True
    if "shopify.com/" in lowered and "/account" in lowered:
        return True
    return False


def storefront_signed_in(page) -> bool:
    """会员页 overview 区是否已是登录态。

    Shopify 托管账户页能打开不代表店面已登录：两条 OAuth 链路的 client_id
    不同，只有 /customer_authentication/ 那条会给 jujubit.ai 种会员会话。
    """
    try:
        return bool(
            page.evaluate(
                """() => {
                    const ov = document.querySelector('.jjb-membership-overview');
                    if (!ov) return false;
                    const text = (ov.innerText || '');
                    if (/log in to view your plan/i.test(text)) return false;
                    return /[\\w.+-]+@[\\w.-]+\\.\\w+/.test(text);
                }"""
            )
        )
    except Exception:
        return False


def _looks_logged_in(page) -> bool:
    try:
        return is_logged_in_url(page.url or "")
    except Exception:
        return False


def _open_pages(context):
    """返回当前还活着的标签页，Account 登录经常会新开 Shopify 页。"""
    alive = []
    for page in context.pages:
        try:
            _ = page.url
        except Exception:
            continue
        alive.append(page)
    return alive


def _find_logged_in_page(context):
    for page in _open_pages(context):
        if _looks_logged_in(page):
            return page
    return None


def _prefill_email(page, email: str) -> bool:
    """在 Shopify 登录页填入邮箱并提交，让窗口直接停在输验证码那一步。

    只省掉打字，验证码仍须本人从邮箱取——脚本不接收邮件。
    """
    try:
        field = page.locator(
            'input[type="email"], input[name="account[email]"], input[name="email"]'
        ).first
        field.wait_for(state="visible", timeout=20_000)
        field.fill(email)
        submit = page.locator(
            'button[type="submit"], button:has-text("Continue"), button:has-text("Submit")'
        ).first
        if submit.count():
            submit.click()
        else:
            field.press("Enter")
        page.wait_for_timeout(4_000)
        return True
    except Exception as error:
        print(f"邮箱预填失败，请在窗口里手动输入：{error}", flush=True)
        return False


def _page_urls(context) -> str:
    urls = []
    for page in _open_pages(context):
        try:
            urls.append(page.url or "(empty)")
        except Exception:
            urls.append("(closed)")
    return " | ".join(urls) or "(no pages)"


def main(argv: list[str] | None = None) -> int:
    import argparse

    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser(description="导出 JuJuBit 登录态")
    parser.add_argument(
        "--email",
        default="",
        help="预填到 Shopify 登录页的邮箱；验证码仍需本人从邮箱取。",
    )
    args = parser.parse_args(argv)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print("正在打开独立浏览器窗口，走店面侧账户登录入口。", flush=True)
    if args.email:
        print(f"会自动填入邮箱 {args.email} 并提交，你只需要输邮箱里的验证码。", flush=True)
    else:
        print("请在这个窗口里用测试邮箱完成 Shopify 登录（邮箱验证码）。", flush=True)
    print("成功标志：会员页 overview 显示你的邮箱，而不是 Log in to view your plan。", flush=True)
    print(f"最长等待 {WAIT_SECONDS // 60} 分钟；完成后脚本自动保存，不要强杀窗口。", flush=True)

    with sync_playwright() as driver:
        context = driver.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1280, "height": 800},
            channel="chrome",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(STOREFRONT_LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
        if args.email and not _looks_logged_in(page):
            if _prefill_email(page, args.email):
                print("邮箱已提交，请在窗口里输入邮箱收到的验证码。", flush=True)
        logged_in_page = None
        deadline = time.time() + WAIT_SECONDS
        last_report = 0.0
        while time.time() < deadline:
            if not _open_pages(context):
                print("浏览器窗口已关闭。", flush=True)
                break
            logged_in_page = _find_logged_in_page(context)
            if logged_in_page is not None:
                break
            now = time.time()
            if now - last_report >= 30:
                remaining = int(deadline - now)
                print(
                    f"仍在等待登录（剩余 {remaining // 60} 分钟）：{_page_urls(context)[:160]}",
                    flush=True,
                )
                last_report = now
            time.sleep(2)

        if logged_in_page is None:
            print("未检测到登录完成（等待超时或窗口被关闭）。", flush=True)
            print("必须走完验证码，回到 jujubit.ai 才算这一跳结束。", flush=True)
            context.close()
            return 1

        print(f"已离开登录页：{logged_in_page.url[:100]}", flush=True)
        logged_in_page.wait_for_timeout(3_000)
        # 最终判定用会员页 overview：Shopify 托管账户页能打开不代表店面已登录。
        try:
            logged_in_page.goto(
                PAYWALL_URL, wait_until="domcontentloaded", timeout=60_000
            )
            logged_in_page.wait_for_timeout(6_000)
        except Exception as error:
            print(f"会员页回访失败：{error}", flush=True)
            context.close()
            return 1
        if not storefront_signed_in(logged_in_page):
            print("店面侧仍未登录：会员页 overview 还是 Log in to view your plan。", flush=True)
            print("这份会话不能用于 membership_session 用例，未写入文件。", flush=True)
            context.close()
            return 1
        print("会员页 overview 已是登录态。", flush=True)

        payload = context.storage_state()
        OUTPUT.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        OUTPUT.chmod(0o600)
        context.close()

    summary = _cookie_summary(json.loads(OUTPUT.read_text(encoding="utf-8")))
    print(f"已写入 {OUTPUT}", flush=True)
    print(summary, flush=True)
    print(
        "更新 GitHub Secret：gh secret set PLAYWRIGHT_STORAGE_STATE_JSON < "
        "artifacts/auth/storage-state.json",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
