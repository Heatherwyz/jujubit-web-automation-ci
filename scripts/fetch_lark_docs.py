#!/usr/bin/env python3
"""把飞书知识库文档拉成本地 Markdown，供设计测试用例时引用。

为什么需要：需求写在飞书 wiki 里，网页版需要登录会话，抓取工具只能拿到登录页。
用开放平台应用凭据走 API 才能读到正文。文档落到 docs/requirements/ 后，需求与
用例一起进版本管理，需求变更能看出 diff。

需要的凭据（走环境变量，不写进仓库）：
    LARK_APP_ID / LARK_APP_SECRET

需要的应用权限（在开放平台「权限管理」里开通并发布版本）：
    wiki:wiki:readonly   读取知识库节点
    docx:document:readonly  读取云文档内容

用法：
    LARK_APP_ID=cli_xxx LARK_APP_SECRET=yyy \\
        python scripts/fetch_lark_docs.py \\
        --token <LARK_FIRST_DOC_TOKEN> --token I6dfwGeN7iRDiAkYVz6c3V3PnYc

    # 或从文件读取链接（每行一个 wiki 链接）
    python scripts/fetch_lark_docs.py --links-file docs/requirements/links.txt

安全约束：只允许 https 且主机在飞书官方允许列表内，并拒绝解析到环回、私有、
保留地址的主机；输出文件名由 token 白名单字符构成，不接受路径分隔符。
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "docs" / "requirements"

# 只允许访问飞书官方 API 主机。
ALLOWED_API_HOSTS = frozenset({"open.feishu.cn", "open.larksuite.com"})
# wiki token 与文档 id 都是字母数字，白名单校验后才拼进 URL 与文件名。
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9]+$")
# 从 wiki 链接里取 token。
WIKI_LINK_RE = re.compile(r"/wiki/([A-Za-z0-9]+)")

API_BASE = "https://open.feishu.cn"
REQUEST_TIMEOUT = 30


class LarkError(RuntimeError):
    """飞书 API 返回业务错误。"""


def _reject_internal_host(host: str) -> None:
    """拒绝环回、私有、链路本地与保留地址，避免请求被指向内网。"""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        # 解析失败交给后续请求报错；这里只拦已知内网目标。
        return
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_loopback
            or address.is_private
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise SystemExit(f"拒绝访问内网地址：{host} -> {address}")


def _validate_api_url(url: str) -> str:
    """只允许 https + 飞书官方主机，并拒绝内网解析。"""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise SystemExit(f"API 必须使用 https，实际为 {parts.scheme!r}")
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in ALLOWED_API_HOSTS:
        raise SystemExit(
            f"API 主机不在允许列表内：{host!r}；"
            f"允许 {', '.join(sorted(ALLOWED_API_HOSTS))}"
        )
    _reject_internal_host(host)
    return url


def _safe_token(value: str, label: str = "token") -> str:
    token = value.strip()
    if not token or not SAFE_TOKEN_RE.match(token):
        raise SystemExit(f"{label} 含非法字符：{value!r}")
    return token


def _request(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    token: str = "",
) -> dict[str, Any]:
    """发一次飞书 API 请求并返回解析后的 JSON。"""
    _validate_api_url(url)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:300]
        raise LarkError(f"HTTP {error.code}：{detail}") from error
    except urllib.error.URLError as error:
        raise LarkError(f"请求失败：{error.reason}") from error
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as error:
        raise LarkError("响应不是合法 JSON") from error
    if parsed.get("code") not in (0, None):
        raise LarkError(f"业务错误 code={parsed.get('code')}：{parsed.get('msg')}")
    return parsed


def get_tenant_token(app_id: str, app_secret: str) -> str:
    """用应用凭据换 tenant_access_token。"""
    result = _request(
        f"{API_BASE}/open-apis/auth/v3/tenant_access_token/internal",
        method="POST",
        payload={"app_id": app_id, "app_secret": app_secret},
    )
    token = result.get("tenant_access_token", "")
    if not token:
        raise LarkError("未取得 tenant_access_token，请检查 app_id / app_secret")
    return token


def resolve_wiki_node(wiki_token: str, token: str) -> dict[str, str]:
    """把 wiki token 解析为实际文档 id 与标题。"""
    query = urllib.parse.urlencode({"token": _safe_token(wiki_token, "wiki token")})
    result = _request(
        f"{API_BASE}/open-apis/wiki/v2/spaces/get_node?{query}", token=token
    )
    node = (result.get("data") or {}).get("node") or {}
    return {
        "obj_token": node.get("obj_token", ""),
        "obj_type": node.get("obj_type", ""),
        "title": node.get("title", "") or wiki_token,
    }


def fetch_document_markdown(document_id: str, token: str) -> str:
    """取云文档的纯文本内容。

    用 docx raw_content 接口：它返回带层级的纯文本，足以支撑用例设计，
    且比逐 block 拼装稳定得多。
    """
    doc_id = _safe_token(document_id, "document id")
    result = _request(
        f"{API_BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", token=token
    )
    return ((result.get("data") or {}).get("content", "")) or ""


def _slugify(title: str, fallback: str) -> str:
    """生成安全的文件名：保留中英文与数字，其余替换为连字符。"""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", "-", title).strip("-")
    return (cleaned or fallback)[:80]


def collect_tokens(args: argparse.Namespace) -> list[str]:
    """汇总命令行与文件里的 wiki token，保持顺序并去重。"""
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
        token = _safe_token(item, "wiki token")
        if token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="拉取飞书 wiki 文档为本地 Markdown")
    parser.add_argument("--token", action="append", help="wiki token，可重复传入")
    parser.add_argument("--links-file", help="含 wiki 链接的文本文件（每行一个）")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="输出目录，默认 docs/requirements",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="两次请求之间的最小间隔秒数，避免触发频控",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    app_id = os.getenv("LARK_APP_ID", "").strip()
    app_secret = os.getenv("LARK_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        print(
            "未配置 LARK_APP_ID / LARK_APP_SECRET。\n"
            "请在飞书开放平台创建应用，开通 wiki:wiki:readonly 与 "
            "docx:document:readonly 权限并发布版本后重试。",
            file=sys.stderr,
        )
        return 2

    tokens = collect_tokens(args)
    if not tokens:
        print("未提供任何 wiki token，使用 --token 或 --links-file。", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir = output_dir.resolve()
    if ROOT.resolve() not in output_dir.parents and output_dir != ROOT.resolve():
        raise SystemExit(f"输出目录必须位于仓库内：{output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    access_token = get_tenant_token(app_id, app_secret)
    print(f"已取得访问令牌，开始拉取 {len(tokens)} 篇文档。\n")

    index_lines = ["# 会员需求文档索引", "", "由 scripts/fetch_lark_docs.py 生成。", ""]
    failures = 0
    for position, wiki_token in enumerate(tokens, start=1):
        try:
            node = resolve_wiki_node(wiki_token, access_token)
            if node["obj_type"] != "docx":
                print(f"  [{position}/{len(tokens)}] 跳过非文档节点：{node['obj_type']}")
                continue
            content = fetch_document_markdown(node["obj_token"], access_token)
            name = f"{position:02d}-{_slugify(node['title'], wiki_token)}.md"
            target = output_dir / name
            target.write_text(
                f"# {node['title']}\n\n"
                f"> 来源：https://<LARK_TENANT_HOST>/wiki/{wiki_token}\n\n"
                f"{content}\n",
                encoding="utf-8",
            )
            index_lines.append(f"- [{node['title']}]({name})")
            print(f"  [{position}/{len(tokens)}] {node['title']} -> {name}")
        except (LarkError, SystemExit) as error:
            failures += 1
            print(f"  [{position}/{len(tokens)}] {wiki_token} 失败：{error}", file=sys.stderr)
        if position < len(tokens):
            time.sleep(max(0.0, args.interval))

    (output_dir / "README.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    print(f"\n完成：成功 {len(tokens) - failures} 篇，失败 {failures} 篇。")
    print(f"输出目录：{output_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
