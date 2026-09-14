#!/usr/bin/env python3
"""Measure response timing for URLs recorded in the JuJuBit link inventory."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import re
import subprocess
import time
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

# 直接以脚本方式运行时 scripts/ 不在包路径上，因此按文件位置补一次仓库根目录。
if __package__:
    from scripts._metrics import percentile as _shared_percentile
else:  # pragma: no cover - 仅在 python scripts/xxx.py 直接执行时走到
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts._metrics import percentile as _shared_percentile


LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)]+)\)")
METRIC_SEPARATOR = "|"
METRIC_FORMAT = "%{http_code}|%{time_namelookup}|%{time_connect}|%{time_appconnect}|%{time_starttransfer}|%{time_total}|%{size_download}|%{url_effective}"
JUJUBIT_HOSTS = {"jujubit.ai", "www.jujubit.ai"}
ASSET_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".avif", ".mp4", ".webm")


def load_urls(path: Path) -> list[str]:
    urls = []
    seen = set()
    for match in LINK_RE.finditer(path.read_text(encoding="utf-8")):
        url = match.group(1).strip()
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def canonicalize_internal_url(url: str) -> str:
    """将锚点、集合上下文和会员来源参数归并到一个页面目标。"""
    parts = urlsplit(url)
    path = parts.path or "/"
    if "/collections/" in path and "/products/" in path:
        path = path[path.index("/products/"):]
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key in {"entry_page", "return_url"}:
            continue
        query.append((key, value))
    return urlunsplit(("https", "jujubit.ai", path, urlencode(query), ""))


def classify_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.netloc.lower() not in JUJUBIT_HOSTS:
        return "external"
    path = parts.path.lower()
    if path.startswith("/cdn/") or path.endswith(ASSET_SUFFIXES):
        return "asset"
    return "internal"


def load_targets(path: Path, include_external: bool = True) -> list[dict]:
    """读取清单并返回去重后的页面、外部目的地和媒体资源目标。"""
    targets = []
    seen = set()
    for raw_url in load_urls(path):
        kind = classify_url(raw_url)
        url = canonicalize_internal_url(raw_url) if kind == "internal" else raw_url.split("#", 1)[0]
        if kind == "external" and not include_external:
            continue
        key = (kind, url)
        if not url or key in seen:
            continue
        seen.add(key)
        targets.append({"url": url, "kind": kind, "source_url": raw_url})
    return targets


def measure(url: str, timeout: float, kind: str = "internal") -> dict:
    started = time.monotonic()
    command = [
        "curl", "-L", "--silent", "--show-error", "--max-time", str(int(timeout)),
        "-A", "JuJuBit-link-performance/1.0", "-o", "/dev/null", "-w", METRIC_FORMAT, url,
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout + 5)
        elapsed = time.monotonic() - started
        fields = completed.stdout.strip().split(METRIC_SEPARATOR)
        if len(fields) != 8:
            raise RuntimeError(completed.stderr.strip() or "curl returned incomplete metrics")
        status, dns, connect, tls, ttfb, total, size, effective = fields
        status_code = int(status)
        total_ms = float(total) * 1000
        return {
            "url": url,
            "kind": kind,
            "effective_url": effective,
            "host": urlparse(url).netloc,
            "status": status_code,
            "dns_ms": round(float(dns) * 1000, 1),
            "connect_ms": round(float(connect) * 1000, 1),
            "tls_ms": round(float(tls) * 1000, 1),
            "ttfb_ms": round(float(ttfb) * 1000, 1),
            "total_ms": round(total_ms, 1),
            "size_bytes": int(float(size)),
            "error": completed.stderr.strip() if completed.returncode else "",
            "ok": completed.returncode == 0 and 200 <= status_code < 400,
            "sample_elapsed_ms": round(elapsed * 1000, 1),
        }
    except Exception as exc:  # noqa: BLE001 - report every URL instead of aborting the run
        return {
            "url": url,
            "kind": kind,
            "effective_url": "",
            "host": urlparse(url).netloc,
            "status": 0,
            "dns_ms": None,
            "connect_ms": None,
            "tls_ms": None,
            "ttfb_ms": None,
            "total_ms": None,
            "size_bytes": 0,
            "error": str(exc),
            "ok": False,
            "sample_elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        }


def percentile(values: list[float], pct: float) -> float | None:
    """委托共用实现，保证与其他性能脚本得出同一个分位数。"""
    result = _shared_percentile(values, pct)
    return None if result is None else round(result, 1)


def build_report(results: list[dict], source: Path, started_at: str, timeout: float, concurrency: int) -> str:
    valid = [item for item in results if item["status"]]
    passed = [item for item in results if item["ok"]]
    failed = [item for item in results if not item["ok"]]
    total_values = [item["total_ms"] for item in valid if item["total_ms"] is not None]
    ttfb_values = [item["ttfb_ms"] for item in valid if item["ttfb_ms"] is not None]
    internal = [item for item in results if item.get("kind") == "internal"]
    external = [item for item in results if item.get("kind") == "external"]
    assets = [item for item in results if item.get("kind") == "asset"]

    def avg(items: list[dict], key: str) -> float | None:
        values = [item[key] for item in items if item[key] is not None]
        return round(sum(values) / len(values), 1) if values else None

    def group_line(name: str, items: list[dict]) -> str:
        values = [item["total_ms"] for item in items if item["total_ms"] is not None]
        return f"| {name} | {len(items)} | {sum(1 for item in items if item['ok'])} | {avg(items, 'ttfb_ms') or '-'} | {avg(items, 'total_ms') or '-'} | {percentile(values, .95) or '-'} |"

    lines = [
        f"# JuJuBit 站内及外部链接性能测试报告 - {started_at[:10]}",
        "",
        f"> 数据源：`{source}`；采样时间：{started_at}；工具：curl；并发：{concurrency}；单链接超时：{timeout:g}s。",
        "> 指标均为单次请求采样，不代表真实用户 RUM；跨地域、缓存命中、CDN 节点和 WAF 策略会影响结果。",
        "",
        "## 结论摘要",
        "",
        f"- 去重后目标：{len(results)}（站内页面 {len(internal)}、外部目的地 {len(external)}、媒体资源 {len(assets)}）。",
        f"- HTTP 可完成请求：{len(valid)}；达到 2xx/3xx：{len(passed)}；异常或超时：{len(failed)}。",
        f"- 全部有效响应 TTFB：P50 `{percentile(ttfb_values, .50) or '-'} ms`，P95 `{percentile(ttfb_values, .95) or '-'} ms`。",
        f"- 全部有效响应总耗时：P50 `{percentile(total_values, .50) or '-'} ms`，P95 `{percentile(total_values, .95) or '-'} ms`。",
        "- 评估口径：TTFB < 800ms 为较好，800-1800ms 为关注，>1800ms 为高延迟；总耗时 > 3000ms 进入问题清单。",
        "",
        "## 分组结果",
        "",
        "| 类型 | 数量 | 通过 | 平均 TTFB(ms) | 平均总耗时(ms) | P95 总耗时(ms) |",
        "|---|---:|---:|---:|---:|---:|",
        group_line("站内", internal),
        group_line("站外", external),
        group_line("媒体资源", assets),
        "",
        "## 高延迟与异常链接",
        "",
        "| URL | 状态 | TTFB(ms) | 总耗时(ms) | 大小(bytes) | 结果/错误 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    problem_items = sorted(
        [item for item in results if not item["ok"] or (item["total_ms"] or 0) > 3000],
        key=lambda item: item["total_ms"] or float("inf"), reverse=True,
    )
    if problem_items:
        for item in problem_items:
            lines.append(
                f"| {item['url']} | {item['status'] or '-'} | {item['ttfb_ms'] or '-'} | {item['total_ms'] or '-'} | {item['size_bytes']} | {item['error'] or ('通过但总耗时超过 3000ms' if item['ok'] else '请求失败')} |"
            )
    else:
        lines.append("| 无 | - | - | - | - | 未发现异常 |")
    lines.extend(["", "## 完整采样明细", "", "| URL | 类型 | 状态 | TTFB(ms) | 总耗时(ms) | 大小(bytes) |", "|---|---|---:|---:|---:|---:|"])
    for item in results:
        kind = item.get("kind", "unknown")
        lines.append(f"| {item['url']} | {kind} | {item['status'] or '-'} | {item['ttfb_ms'] or '-'} | {item['total_ms'] or '-'} | {item['size_bytes']} |")
    lines.extend(["", "## 测试限制", "", "- 本次是执行环境所在网络的单轮 HTTP 采样，不是美国住宅用户 RUM，也不是 WebPageTest/GTmetrix 的美国节点结果。", "- 页面性能只统计 HTML 页面目标；媒体资源单列，外部目的地仅表示从当前执行环境可达性。", "- 外部链接由第三方服务控制，异常结果需结合目标站点所在地、WAF、重定向和服务可用性复测。", "- 建议对问题链接从目标用户主要地区重复采样 3-5 轮，并使用 Lighthouse/真实用户监控补充 LCP、CLS、INP。", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=Path("docs/JuJuBit-站内可跳转链接清单.md"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--internal-only", action="store_true", help="只测试归一化后的 JuJuBit 页面")
    args = parser.parse_args()
    started = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")
    targets = load_targets(args.inventory, include_external=not args.internal_only)
    results = [None] * len(targets)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(measure, target["url"], args.timeout, target["kind"]): index
            for index, target in enumerate(targets)
        }
        for future in concurrent.futures.as_completed(futures):
            results[futures[future]] = future.result()
    results = [item for item in results if item]
    date = started[:10]
    output = args.output or Path(f"artifacts/performance/jujubit-link-performance-{date}.md")
    json_output = args.json_output or output.with_suffix(".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report(results, args.inventory, started, args.timeout, args.concurrency), encoding="utf-8")
    json_output.write_text(json.dumps({"started_at": started, "source": str(args.inventory), "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"count": len(results), "report": str(output), "json": str(json_output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
