#!/usr/bin/env python3
"""打开独立浏览器窗口登录飞书，用持久化 profile 保留登录态。

为什么需要：需求写在飞书 wiki 里，未登录时任何抓取都只会拿到登录页。这里起一个
与用户日常使用的 Chrome 完全独立的浏览器实例（独立 profile、独立窗口），扫码
一次即可，之后读取脚本复用同一个 profile。

用持久化 profile 而不是导出 storage_state：登录态由浏览器自己写入 profile 目录，
不依赖脚本判断"何时算登录成功"（飞书登录会经过多次跳转，靠 URL 判断容易误判）。

用法：
    python scripts/lark_login.py          # 扫码登录，登录完成后手动关闭窗口
    python scripts/lark_login.py --check  # 只检查当前 profile 是否已登录

profile 存在 .lark-session/profile（已在 .gitignore 中忽略，含身份凭据）。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / ".lark-session" / "profile"
# 租户域名与首篇文档 token 都从环境变量读，不硬编码：它们标识公司的飞书
# 空间与具体内部文档。用法：
#   export LARK_TENANT_HOST=<租户>.feishu.cn
#   export LARK_FIRST_DOC_TOKEN=<wiki token>
LARK_TENANT_HOST = os.environ.get("LARK_TENANT_HOST", "")
_FIRST_DOC_TOKEN = os.environ.get("LARK_FIRST_DOC_TOKEN", "")
FIRST_DOC = (
    f"https://{LARK_TENANT_HOST}/wiki/{_FIRST_DOC_TOKEN}"
    if LARK_TENANT_HOST and _FIRST_DOC_TOKEN
    else ""
)
LOGIN_HOST = "accounts.feishu.cn"


def _launch(headless: bool):
    """打开持久化 profile 的浏览器上下文。"""
    from playwright.sync_api import sync_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    driver = sync_playwright().start()
    context = driver.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        viewport={"width": 1000, "height": 820},
        args=[] if headless else ["--window-position=700,40"],
    )
    return driver, context


def _require_first_doc() -> str:
    """返回首篇文档地址；缺环境变量时明确报错。

    不能让空串流到 page.goto()：那会静默打开空白页，然后报"未登录"，
    把配置缺失误导成登录态问题。
    """
    if not FIRST_DOC:
        raise SystemExit(
            "缺少飞书租户配置。请先设置环境变量：\n"
            "  export LARK_TENANT_HOST=<租户>.feishu.cn\n"
            "  export LARK_FIRST_DOC_TOKEN=<wiki token>\n"
            "这两个值标识公司内部飞书空间，不写入仓库。"
        )
    return FIRST_DOC


def check_login() -> int:
    """无头打开文档，判断 profile 里的登录态是否仍然有效。"""
    first_doc = _require_first_doc()
    driver, context = _launch(headless=True)
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(first_doc, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(4_000)
        if LOGIN_HOST in page.url:
            print("未登录：仍被重定向到飞书登录页。")
            print("请先运行：python scripts/lark_login.py")
            return 1
        title = page.title()
        text = page.locator("body").inner_text()[:120].replace("\n", " ")
        print("已登录。")
        print(f"  文档标题：{title[:70]}")
        print(f"  正文预览：{text}")
        return 0
    finally:
        context.close()
        driver.stop()


def interactive_login() -> int:
    """打开有界面窗口供扫码，轮询确认登录成功后主动优雅关闭上下文。

    必须由脚本自己 context.close()：外部强杀进程会让 Chromium 来不及把 cookie
    刷进 profile 目录，导致下次仍是未登录状态（踩过这个坑）。
    """
    import time

    first_doc = _require_first_doc()
    driver, context = _launch(headless=False)
    logged_in = False
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(first_doc, wait_until="domcontentloaded", timeout=60_000)
        print("已打开独立浏览器窗口（屏幕右侧），请扫码登录飞书。", flush=True)
        print("登录成功后脚本会自动检测并保存，无需手动关窗。", flush=True)

        deadline = time.time() + 600
        while time.time() < deadline:
            try:
                if LOGIN_HOST not in page.url:
                    # 已离开登录域名，再等正文渲染，确认不是中间跳转。
                    page.wait_for_timeout(5_000)
                    if LOGIN_HOST not in page.url:
                        logged_in = True
                        break
            except Exception:
                # 页面被用户关闭或正在跳转，稍后重试。
                break
            time.sleep(2)

        if logged_in:
            print(f"\n检测到登录成功：{page.title()[:70]}", flush=True)
            # 多等一会儿让飞书写完所有 cookie 与本地存储。
            page.wait_for_timeout(5_000)
    finally:
        # 优雅关闭，确保 profile 刷盘。
        try:
            context.close()
        except Exception:
            pass
        driver.stop()

    if logged_in:
        print("登录态已保存到 profile。")
        return 0
    print("\n未检测到登录完成（等待 10 分钟超时或窗口被关闭）。")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="飞书登录与登录态检查")
    parser.add_argument(
        "--check", action="store_true", help="只检查当前 profile 是否已登录"
    )
    args = parser.parse_args(argv)
    return check_login() if args.check else interactive_login()


if __name__ == "__main__":
    sys.exit(main())
