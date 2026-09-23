#!/usr/bin/env python3
"""用已登录的浏览器 profile 读取飞书 wiki 文档正文，落盘为本地 Markdown。

为什么走浏览器而不是开放平台 API：API 需要创建自建应用、开通权限并等管理员审批。
这里复用 scripts/lark_login.py 扫码后留下的持久化 profile，直接以真实登录身份
渲染页面再取正文，省掉审批流程。

飞书文档是前端渲染的，必须等正文节点出现后再取文本，不能只看 HTML 源码。

用法：
    python scripts/read_lark_docs.py --links-file docs/requirements/links.txt
    python scripts/read_lark_docs.py --token <LARK_FIRST_DOC_TOKEN>
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / ".lark-session" / "profile"
DEFAULT_OUTPUT = ROOT / "docs" / "requirements"
# 飞书租户域名从环境变量读，不硬编码在仓库里：它标识公司的飞书空间，
# 属于内部信息。用法：export LARK_TENANT_HOST=<租户>.feishu.cn
LARK_TENANT_HOST = os.environ.get("LARK_TENANT_HOST", "")
WIKI_BASE = f"https://{LARK_TENANT_HOST}/wiki/" if LARK_TENANT_HOST else ""
LOGIN_HOST = "accounts.feishu.cn"

SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9]+$")
WIKI_LINK_RE = re.compile(r"/wiki/([A-Za-z0-9]+)")
# 飞书文档正文容器；多个候选以兼容不同文档类型。
CONTENT_SELECTORS = (
    ".docx-page-block-children",
    ".page-block-children",
    ".doc-content",
    "[data-page-id]",
    ".etherpad-container",
)


def _safe_token(value: str) -> str:
    token = value.strip()
    if not token or not SAFE_TOKEN_RE.match(token):
        raise SystemExit(f"wiki token 含非法字符：{value!r}")
    return token


def _slugify(title: str, fallback: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", "-", title).strip("-")
    return (cleaned or fallback)[:70]


def collect_tokens(args: argparse.Namespace) -> list[str]:
    raw: list[str] = list(args.token or [])
    if args.links_file:
        path = Path(args.links_file)
        if not path.is_absolute():
            path = ROOT / path
        resolved = path.resolve()
        if ROOT.resolve() not in resolved.parents:
            raise SystemExit(f"链接文件必须位于仓库内：{resolved}")
        for line in resolved.read_text(encoding="utf-8").splitlines():
            match = WIKI_LINK_RE.search(line.strip())
            if match:
                raw.append(match.group(1))
    seen: set[str] = set()
    ordered: list[str] = []
    for item in raw:
        token = _safe_token(item)
        if token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


def _extract_text(page) -> str:
    """等正文渲染完成后取纯文本。"""
    for selector in CONTENT_SELECTORS:
        try:
            page.wait_for_selector(selector, timeout=8_000)
            break
        except Exception:
            continue
    # 文档很长时需要滚动触发懒加载。
    for _ in range(12):
        page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        page.wait_for_timeout(600)
    page.wait_for_timeout(1_500)

    for selector in CONTENT_SELECTORS:
        node = page.locator(selector).first
        if node.count():
            text = node.inner_text()
            if len(text.strip()) > 50:
                return text
    return page.locator("body").inner_text()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="读取飞书 wiki 文档为本地 Markdown")
    parser.add_argument("--token", action="append", help="wiki token，可重复")
    parser.add_argument("--links-file", help="含 wiki 链接的文本文件")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--headed",
        action="store_true",
        help="显示浏览器窗口。飞书会拒绝无头浏览器的登录态，所以抓取时需要用它",
    )
    args = parser.parse_args(argv)

    if not PROFILE_DIR.is_dir():
        print(
            "未找到登录 profile，请先运行：python scripts/lark_login.py",
            file=sys.stderr,
        )
        return 2

    tokens = collect_tokens(args)
    if not tokens:
        print("未提供任何 wiki token。", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir = output_dir.resolve()
    if ROOT.resolve() not in output_dir.parents:
        raise SystemExit(f"输出目录必须位于仓库内：{output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    index_lines = ["# 会员需求文档（从飞书 wiki 抓取）", ""]
    failures = 0

    with sync_playwright() as driver:
        context = driver.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=not args.headed,
            viewport={"width": 1400, "height": 1000},
            # 窗口放到屏幕右侧，避免遮挡左边的对话。
            args=[] if not args.headed else ["--window-position=700,40"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            for position, token in enumerate(tokens, start=1):
                url = f"{WIKI_BASE}{token}"
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(4_000)
                    if LOGIN_HOST in page.url:
                        print(
                            f"  [{position}/{len(tokens)}] {token} 需要登录，"
                            "请重新运行 scripts/lark_login.py",
                            file=sys.stderr,
                        )
                        failures += 1
                        continue
                    title = (page.title() or token).replace(" - 三启万物云文档", "").strip()
                    body = _extract_text(page)
                    name = f"{position:02d}-{_slugify(title, token)}.md"
                    (output_dir / name).write_text(
                        f"# {title}\n\n> 来源：{url}\n\n{body}\n", encoding="utf-8"
                    )
                    index_lines.append(f"- [{title}]({name})")
                    print(
                        f"  [{position}/{len(tokens)}] {title[:44]} "
                        f"-> {name}（{len(body)} 字）"
                    )
                except Exception as error:
                    failures += 1
                    print(
                        f"  [{position}/{len(tokens)}] {token} 失败：{str(error)[:110]}",
                        file=sys.stderr,
                    )
                time.sleep(1.0)
        finally:
            context.close()

    (output_dir / "README.md").write_text(
        "\n".join(index_lines) + "\n", encoding="utf-8"
    )
    print(f"\n完成：成功 {len(tokens) - failures} 篇，失败 {failures} 篇。")
    print(f"输出目录：{output_dir}")
    return 1 if failures == len(tokens) else 0


if __name__ == "__main__":
    sys.exit(main())
