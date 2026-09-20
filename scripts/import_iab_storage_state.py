#!/usr/bin/env python3
"""从 ZCode 内置浏览器的 profile 直接提取登录态，免去重复手工登录。

为什么需要：Shopify Customer Accounts 的会话凭据是 HttpOnly（`_shopify_essential`），
页面脚本、内置窗口的自动化接口、DevTools 的 Cookie 面板都拿不到值。内置浏览器
的接口只暴露 evaluate/locator，没有 storageState()，也没开 CDP 端口。

但它的 Cookie 存在 Electron partition 目录的 SQLite 里，且 value 列是明文
（encrypted_value 为空）。所以已经在内置窗口登录过时，直接读这个库就能拼出
Playwright 的 storage-state，不必再走一遍邮箱验证码。

用法：
    .venv/bin/python scripts/import_iab_storage_state.py            # 提取并校验
    .venv/bin/python scripts/import_iab_storage_state.py --no-verify  # 只提取

校验的是店面会员会话，不是 Shopify 托管账户页：两条 OAuth 链路的 client_id
不同，只有 /customer_authentication/ 那条会让会员页 overview 显示邮箱。
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "auth" / "storage-state.json"
IAB_COOKIES = (
    Path.home()
    / "Library"
    / "Application Support"
    / "ZCode"
    / "session"
    / "Partitions"
    / "zcode-embedded-browser"
    / "Cookies"
)
PAYWALL_URL = "https://jujubit.ai/pages/vip-program?entry_page=header"
# 只保留站点与 Shopify 账户域，不把浏览器里其它站点的 Cookie 带进测试产物。
WANTED_HOSTS = frozenset(
    {"jujubit.ai", ".jujubit.ai", "shopify.com", ".shopify.com"}
)
# Chrome 纪元是 1601-01-01，Unix 纪元差 11644473600 秒。
CHROME_EPOCH_OFFSET = 11_644_473_600
SAMESITE = {-1: "Lax", 0: "None", 1: "Lax", 2: "Strict"}


def chrome_us_to_unix(chrome_us: int) -> float:
    """Chrome 的微秒时间戳转 Unix 秒；0 表示会话 Cookie，用 -1 表达。"""
    if not chrome_us:
        return -1
    return (chrome_us / 1_000_000) - CHROME_EPOCH_OFFSET


def _fetch_rows(db_copy: Path) -> list[tuple]:
    """从副本读出全部 Cookie 行；域名筛选在 Python 侧做。

    读副本而不是原库：浏览器运行时持有写锁，直接打开会 database is locked。
    """
    conn = sqlite3.connect(str(db_copy))
    try:
        return conn.execute(
            "SELECT host_key, name, value, path, expires_utc, is_secure, is_httponly, samesite FROM cookies"
        ).fetchall()
    finally:
        conn.close()


def read_cookies(db_path: Path) -> list[dict]:
    """把内置浏览器的 Cookie 转成 Playwright storage-state 的 cookies 结构。"""
    workdir = Path(tempfile.mkdtemp(prefix="iab-cookies-"))
    try:
        copy = workdir / "Cookies"
        shutil.copy2(db_path, copy)
        rows = _fetch_rows(copy)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    cookies = []
    for host, name, value, path, expires, secure, httponly, samesite in rows:
        if host not in WANTED_HOSTS or not value:
            continue
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": host,
                "path": path,
                "expires": chrome_us_to_unix(expires),
                "httpOnly": bool(httponly),
                "secure": bool(secure),
                "sameSite": SAMESITE.get(samesite, "Lax"),
            }
        )
    return cookies


def has_storefront_session(cookies: list[dict]) -> bool:
    """jujubit.ai 域下必须有 _shopify_essential，否则店面侧不算登录。"""
    return any(
        cookie["name"] == "_shopify_essential"
        and cookie["domain"].lstrip(".") == "jujubit.ai"
        for cookie in cookies
    )


def describe(cookies: list[dict]) -> str:
    """只汇总名字与数量，不打印 Cookie 值。"""
    essential = [c for c in cookies if "essential" in c["name"]]
    return (
        f"cookies={len(cookies)} "
        f"storefront_session={has_storefront_session(cookies)} "
        f"essential={len(essential)}"
    )


def verify_storefront(state_path: Path) -> bool:
    """用导出的文件实际打开会员页，确认 overview 不再要求登录。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                storage_state=str(state_path),
                viewport={"width": 1440, "height": 900},
            )
            page = context.new_page()
            page.goto(PAYWALL_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(7_000)
            info = page.evaluate(
                """() => {
                    const ov = document.querySelector('.jjb-membership-overview');
                    const text = ov ? (ov.innerText || '') : '';
                    const m = text.match(/[\\w.+-]+@[\\w.-]+\\.\\w+/);
                    return {
                        hasOverview: !!ov,
                        needsLogin: /log in to view your plan/i.test(text),
                        email: m ? m[0] : null,
                    };
                }"""
            )
            context.close()
        finally:
            browser.close()

    if not info["hasOverview"]:
        print("会员页没有 overview 区，无法判定登录态。", flush=True)
        return False
    if info["needsLogin"] or not info["email"]:
        print("店面侧未登录：overview 仍显示 Log in to view your plan。", flush=True)
        return False
    print(f"店面会员会话有效，overview 账号：{info['email']}", flush=True)
    return True


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="从内置浏览器 profile 提取 JuJuBit 登录态"
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="只提取，不打开站点校验（离线场景用）。",
    )
    args = parser.parse_args(argv)

    if not IAB_COOKIES.is_file():
        print(f"找不到内置浏览器 Cookie 库：{IAB_COOKIES}", flush=True)
        print("请确认已在内置窗口登录过 JuJuBit。", flush=True)
        return 1

    cookies = read_cookies(IAB_COOKIES)
    if not cookies:
        print("内置浏览器里没有 jujubit.ai / shopify.com 的 Cookie。", flush=True)
        return 1
    if not has_storefront_session(cookies):
        print("缺少 jujubit.ai 域的 _shopify_essential——店面侧没有登录。", flush=True)
        print("请先在内置窗口打开会员页并完成登录，再重跑本脚本。", flush=True)
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps({"cookies": cookies, "origins": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    OUTPUT.chmod(0o600)
    print(f"已写入 {OUTPUT}", flush=True)
    print(describe(cookies), flush=True)

    if not args.no_verify and not verify_storefront(OUTPUT):
        return 1

    print(
        "更新 GitHub Secret：gh secret set PLAYWRIGHT_STORAGE_STATE_JSON < "
        "artifacts/auth/storage-state.json",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
