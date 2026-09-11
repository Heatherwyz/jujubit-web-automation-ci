#!/usr/bin/env python3
"""低频巡检链接清单中的站内 HTML 页面。

这个脚本不是 Lighthouse、WebPageTest 或真实浏览器性能测试。它只做轻量的
HTTP 可用性/首字节巡检，帮助从链接清单中找出错误状态、重定向和明显的服务端
等待。为避免把 Shopify 页面和 CDN 图片全部下载下来，默认先发 HEAD；HEAD 不
可用时才发一个 `Range: bytes=0-0` 的 GET，并在读取少量响应头后立即关闭连接。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import re
import socket
import ssl
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import (
    parse_qsl,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)
from urllib.request import Request, urlopen


CANONICAL_HOSTS = {"jujubit.ai", "www.jujubit.ai"}
CANONICAL_HOST = "jujubit.ai"
LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)]+)\)")
ASSET_PATH_RE = re.compile(
    r"\.(?:avif|css|csv|gif|ico|jpe?g|js|json|map|mp[34]|pdf|png|svg|webm|webp|woff2?|zip)$",
    re.IGNORECASE,
)
TRACKING_QUERY_KEYS = {
    "_fd",
    "_sc",
    "_sid",
    "_ss",
    "_y",
    "pb",
    "preview_key",
    "view",
}


@dataclass
class ProbeResult:
    url: str
    final_url: str = ""
    method: str = ""
    status: int = 0
    content_type: str = ""
    content_length: int | None = None
    redirects: int = 0
    ttfb_ms: float | None = None
    total_ms: float | None = None
    location: str = ""
    ok: bool = False
    category: str = "站内 HTML"
    error: str = ""


def _canonical_query(query: str) -> str:
    """保留功能参数（variant、page、return_url 等），移除追踪参数。"""
    pairs = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        lower_key = key.lower()
        if lower_key.startswith("utm_") or lower_key in TRACKING_QUERY_KEYS:
            continue
        # Shopify 有时把同一参数重复拼接；同名同值只保留一次。
        if (key, value) not in pairs:
            pairs.append((key, value))
    return urlencode(sorted(pairs), doseq=True)


def normalize_url(raw_url: str) -> str | None:
    """将清单中的绝对链接归一化为可巡检的站内页面 URL。"""
    try:
        parts = urlsplit(raw_url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if host not in CANONICAL_HOSTS or parts.scheme.lower() not in {"http", "https"}:
        return None

    path = parts.path or "/"
    # 集合商品链接最终落到同一个商品详情页；统一到 canonical Shopify route。
    match = re.match(r"^/collections/[^/]+/products(/.*)$", path, re.IGNORECASE)
    if match:
        path = "/products" + match.group(1)
    if path != "/":
        path = "/" + path.strip("/")

    # 锚点不改变服务器返回的 HTML，不能作为独立性能样本。
    query = _canonical_query(parts.query)
    # 会员页的 entry_page / return_url 只决定操作完成后的返回位置，页面本身相同。
    # 合并它们可以避免同一个 HTML 被多次请求，也不会漏掉一个独立落地页。
    if path == "/pages/vip-program":
        query = ""
    if ASSET_PATH_RE.search(path) or path.lower().startswith("/cdn/"):
        return None
    return urlunsplit(("https", CANONICAL_HOST, path, query, ""))


def load_urls(path: Path) -> tuple[list[str], dict[str, int]]:
    """读取 Markdown 链接，并返回去重后的页面地址及跳过分类统计。"""
    raw_urls = LINK_RE.findall(path.read_text(encoding="utf-8"))
    normalized: list[str] = []
    seen: set[str] = set()
    skipped = {"站外/非 HTTP": 0, "站内媒体或非 HTML": 0, "无效 URL": 0}
    for raw in raw_urls:
        try:
            parts = urlsplit(raw.strip())
        except ValueError:
            skipped["无效 URL"] += 1
            continue
        host = (parts.hostname or "").lower()
        if host not in CANONICAL_HOSTS:
            skipped["站外/非 HTTP"] += 1
            continue
        value = normalize_url(raw)
        if value is None:
            skipped["站内媒体或非 HTML"] += 1
            continue
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized, skipped


def _header(headers: object, name: str) -> str:
    try:
        return str(headers.get(name, ""))  # type: ignore[attr-defined]
    except AttributeError:
        return ""


def _content_length(headers: object) -> int | None:
    value = _header(headers, "Content-Length")
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _probe_once(url: str, method: str, timeout: float) -> ProbeResult:
    started = time.monotonic()
    request = Request(
        url,
        method=method,
        headers={
            "User-Agent": "JuJuBit-site-html-probe/1.0 (+low-rate; no full-page download)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            **({"Range": "bytes=0-0"} if method == "RANGE" else {}),
        },
    )
    actual_method = "HEAD" if method == "HEAD" else "GET(range 0-0)"
    try:
        if method == "RANGE":
            request = Request(
                url,
                method="GET",
                headers={
                    "User-Agent": "JuJuBit-site-html-probe/1.0 (+low-rate; no full-page download)",
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                    "Range": "bytes=0-0",
                },
            )
        with urlopen(request, timeout=timeout) as response:
            # 读取极少量数据即可让 urllib 完成首字节计时；随后上下文管理器会关闭连接。
            if method == "RANGE":
                response.read(1)
            elapsed = (time.monotonic() - started) * 1000
            final_url = response.geturl()
            status = int(getattr(response, "status", 200))
            return ProbeResult(
                url=url,
                final_url=final_url,
                method=actual_method,
                status=status,
                content_type=_header(response.headers, "Content-Type"),
                content_length=_content_length(response.headers),
                redirects=0,
                ttfb_ms=round(elapsed, 1),
                total_ms=round(elapsed, 1),
                location=_header(response.headers, "Location"),
                ok=200 <= status < 400,
            )
    except HTTPError as exc:
        elapsed = (time.monotonic() - started) * 1000
        return ProbeResult(
            url=url,
            final_url=exc.geturl(),
            method=actual_method,
            status=int(exc.code),
            content_type=_header(exc.headers, "Content-Type"),
            content_length=_content_length(exc.headers),
            ttfb_ms=round(elapsed, 1),
            total_ms=round(elapsed, 1),
            location=_header(exc.headers, "Location"),
            ok=False,
            error=f"HTTP {exc.code}",
        )
    except (TimeoutError, socket.timeout) as exc:
        elapsed = (time.monotonic() - started) * 1000
        return ProbeResult(url=url, method=actual_method, total_ms=round(elapsed, 1), error=f"超时: {exc or 'timeout'}")
    except (URLError, ssl.SSLError, OSError) as exc:
        elapsed = (time.monotonic() - started) * 1000
        reason = getattr(exc, "reason", exc)
        return ProbeResult(url=url, method=actual_method, total_ms=round(elapsed, 1), error=str(reason))


def probe(url: str, timeout: float) -> ProbeResult:
    """HEAD 优先；仅在服务器拒绝 HEAD 时发一个字节范围请求。"""
    head = _probe_once(url, "HEAD", timeout)
    if head.status not in {405, 501} and head.status != 0:
        return head
    ranged = _probe_once(url, "RANGE", timeout)
    if head.status and ranged.status == 0:
        ranged.error = f"HEAD 返回 {head.status}；Range 请求失败: {ranged.error}"
    return ranged


def _percentile(values: Iterable[float], pct: float) -> float | None:
    values = sorted(values)
    if not values:
        return None
    index = min(len(values) - 1, round((len(values) - 1) * pct))
    return round(values[index], 1)


def build_report(
    results: list[ProbeResult],
    source: Path,
    started_at: str,
    timeout: float,
    concurrency: int,
    delay: float,
    skipped: dict[str, int],
) -> str:
    attempted = [item for item in results if item.category == "站内 HTML"]
    rate_limited_skips = [item for item in results if item.category == "跳过（429 保护）"]
    valid = [item for item in attempted if item.status]
    good = [item for item in attempted if item.ok]
    ttfb = [item.ttfb_ms for item in valid if item.ttfb_ms is not None]
    lines = [
        f"# JuJuBit 站内 HTML 链接轻量巡检报告（{started_at[:10]}）",
        "",
        f"> 数据源：`{source}`；采样时间：`{started_at}`；方法：HEAD 优先，必要时 Range 0-0；并发：{concurrency}；间隔：{delay:g}s；超时：{timeout:g}s。",
        "> 本报告只表示当前执行环境到 Shopify/CDN 的 HTTP 响应，不等同于美国真实用户的 LCP、INP、CLS 或完整页面加载时间。",
        "",
        "## 汇总",
        "",
        f"- 归一化站内 HTML 页面：**{len(results)}**；实际发起请求：**{len(attempted)}**；收到 HTTP 响应：**{len(valid)}**；2xx/3xx：**{len(good)}**；请求异常：**{len(attempted) - len(good)}**。",
        f"- 429 保护性跳过：**{len(rate_limited_skips)}**（如非 0，需稍后低频重跑，不应把它们当作页面失败）。",
        f"- TTFB（近似首字节到达时间）：P50 `{_percentile(ttfb, .5) or '-'} ms`，P95 `{_percentile(ttfb, .95) or '-'} ms`。",
        "- 归一化规则：移除锚点和追踪参数；集合商品路径统一到 `/products/<handle>`；媒体资源不作为 HTML 页面测试。",
        "",
        "## 清单处理",
        "",
        "| 项目 | 数量 |",
        "|---|---:|",
        f"| 站内 HTML 页面 | {len(results)} |",
        f"| 站外/非 HTTP（未巡检） | {skipped.get('站外/非 HTTP', 0)} |",
        f"| 站内媒体或非 HTML（未巡检） | {skipped.get('站内媒体或非 HTML', 0)} |",
        f"| 无效 URL（未巡检） | {skipped.get('无效 URL', 0)} |",
        "",
        "## 异常或慢响应",
        "",
        "| URL | 方法 | 状态 | TTFB(ms) | 最终 URL | 结果 |",
        "|---|---|---:|---:|---|---|",
    ]
    problem = [item for item in attempted if not item.ok or (item.ttfb_ms or 0) > 1800]
    for item in sorted(problem, key=lambda value: value.ttfb_ms or float("inf"), reverse=True):
        lines.append(
            f"| [{item.url}]({item.url}) | {item.method or '-'} | {item.status or '-'} | {item.ttfb_ms or '-'} | {item.final_url or '-'} | {item.error or ('TTFB > 1800ms' if item.ok else '请求失败')} |"
        )
    if not problem:
        lines.append("| 无 | - | - | - | - | 未发现异常 |")
    lines.extend(
        [
            "",
            "## 完整明细",
            "",
            "| URL | 方法 | 状态 | Content-Type | Content-Length | TTFB(ms) | 最终 URL | 结果 |",
            "|---|---|---:|---|---:|---:|---|---|",
        ]
    )
    for item in results:
        result = item.error or ("通过" if item.ok else "请求失败")
        lines.append(
            f"| [{item.url}]({item.url}) | {item.method or '-'} | {item.status or '-'} | {item.content_type or '-'} | {item.content_length or '-'} | {item.ttfb_ms or '-'} | {item.final_url or '-'} | {result} |"
        )
    lines.extend(
        [
            "",
            "## 使用限制",
            "",
            "- HEAD 被拒绝时的 Range 请求最多读取 1 个字节；若服务器忽略 Range，客户端会在读取后立即关闭连接。",
            "- 默认低并发是为了降低 Shopify 429/WAF 风险；不要把该脚本改成压力测试。",
            "- 需要美国用户口径时，应在 WebPageTest/GTmetrix 美国节点或 RUM 中复测代表页面。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="低频巡检 JuJuBit 链接清单中的站内 HTML 页面")
    parser.add_argument("--inventory", type=Path, default=Path("docs/JuJuBit-站内可跳转链接清单.md"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--delay", type=float, default=0.6, help="每个工作线程请求后的最小等待秒数")
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--limit", type=int, default=0, help="仅调试前 N 条；0 表示完整清单")
    parser.add_argument(
        "--continue-after-429",
        action="store_true",
        help="默认检测到 HTTP 429 后保护性停止后续请求；传此参数才继续。",
    )
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 4:
        parser.error("--concurrency 必须在 1 到 4 之间")
    if args.delay < 0 or args.timeout <= 0:
        parser.error("--delay 不能为负数，--timeout 必须大于 0")

    started = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    urls, skipped = load_urls(args.inventory)
    if args.limit:
        urls = urls[: args.limit]
    results: list[ProbeResult | None] = [None] * len(urls)
    rate_limited = threading.Event()

    def run_one(url: str) -> ProbeResult:
        if rate_limited.is_set() and not args.continue_after_429:
            return ProbeResult(
                url=url,
                category="跳过（429 保护）",
                error="前序请求收到 HTTP 429；为避免扩大限流，本条未发起网络请求。",
            )
        result = probe(url, args.timeout)
        if result.status == 429 and not args.continue_after_429:
            rate_limited.set()
        if args.delay:
            time.sleep(args.delay)
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {executor.submit(run_one, url): index for index, url in enumerate(urls)}
        for future in concurrent.futures.as_completed(futures):
            results[futures[future]] = future.result()
    completed = [item for item in results if item is not None]
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    output = args.output or Path(f"artifacts/performance/jujubit-site-html-probe-{run_id}.md")
    json_output = args.json_output or output.with_suffix(".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        build_report(completed, args.inventory, started, args.timeout, args.concurrency, args.delay, skipped),
        encoding="utf-8",
    )
    json_output.write_text(
        json.dumps(
            {
                "started_at": started,
                "source": str(args.inventory),
                "method": "HEAD then Range 0-0",
                "concurrency": args.concurrency,
                "delay_seconds": args.delay,
                "timeout_seconds": args.timeout,
                "stopped_after_429": rate_limited.is_set() and not args.continue_after_429,
                "skipped": skipped,
                "results": [asdict(item) for item in completed],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"count": len(completed), "report": str(output), "json": str(json_output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
