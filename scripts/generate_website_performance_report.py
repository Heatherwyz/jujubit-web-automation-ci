#!/usr/bin/env python3
"""生成可提交的 JuJuBit 网站性能测试 Markdown 报告。

本脚本只读取已经落盘的 JSON 结果，不会发起网页访问、Pingdom 请求或浏览器测试。
它把两类性质不同的数据明确分开：

* ``site-html-probe.json``：当前执行环境的低频 HTTP 可达性/近似 TTFB 巡检；
* ``pingdom-link-performance-*.json``：Pingdom 美国节点的合成测速结果。

这样即使 Pingdom 全量任务尚未完成，也能生成一份如实标出 ``已完成 / 115`` 的
报告；当 JSON 完整时，报告正文会逐页列出所有 Pingdom 报告链接，不依赖被
``.gitignore`` 忽略的 artifacts 文件供读者查看明细。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATE = "2026-08-19"
CANONICAL_HOSTS = {"jujubit.ai", "www.jujubit.ai"}
TRACKING_QUERY_KEYS = {"_fd", "_sc", "_sid", "_ss", "_y", "pb", "preview_key", "view"}
ASSET_PATH_RE = re.compile(
    r"\.(?:avif|css|csv|gif|ico|jpe?g|js|json|map|mp[34]|pdf|png|svg|webm|webp|woff2?|zip)$",
    re.IGNORECASE,
)


# 这五份 PSI 和一份 GTmetrix 结果已经由人工/浏览器实际取得。保留它们的
# 原始报告链接和当时记录的指标，避免在生成 Markdown 时重新请求第三方服务。
PSI_SAMPLES = (
    {
        "page": "首页",
        "crux": "未通过：LCP 2.9s；INP 162ms；CLS 0；TTFB 0.6s",
        "lab": "43 分；FCP 3.7s；LCP 15.4s；TBT 690ms；CLS 0；SI 7.9s",
        "url": "https://pagespeed.web.dev/analysis/https-jujubit-ai/ugurqflwa0?form_factor=mobile",
    },
    {
        "page": "购物车",
        "crux": "未记录可用的 CrUX 页面级结论",
        "lab": "29 分；FCP 5.4s；LCP 12.9s；TBT 2610ms；CLS 0；SI 8.2s",
        "url": "https://pagespeed.web.dev/analysis/https-jujubit-ai-cart/syr54f036a?form_factor=mobile",
    },
    {
        "page": "集合总览",
        "crux": "通过：LCP 1.9s；INP 129ms；CLS 0；TTFB 0.2s",
        "lab": "37 分；FCP 3.7s；LCP 15.2s；TBT 1390ms；CLS 0；SI 6.4s",
        "url": "https://pagespeed.web.dev/analysis/https-jujubit-ai-collections/zujiy727bu?form_factor=mobile",
    },
    {
        "page": "创作页（Customize Your Own）",
        "crux": "未通过：LCP 2.5s；INP 334ms；CLS 0.61；TTFB 0.3s",
        "lab": "10 分；FCP 5.0s；LCP 17.7s；TBT 1070ms；CLS 0.73；SI 12.1s",
        "url": "https://pagespeed.web.dev/analysis/https-jujubit-ai-products-customize-your-own/rtyppp87ty?form_factor=mobile",
    },
    {
        "page": "模板集合页",
        "crux": "通过：LCP 1.9s；INP 126ms；CLS 0；TTFB 0.3s",
        "lab": "44 分；FCP 3.7s；LCP 11.6s；TBT 750ms；CLS 0；SI 6.4s",
        "url": "https://pagespeed.web.dev/analysis/https-jujubit-ai-collections-templates-create-your-own/p3y1vhrkkj?form_factor=mobile",
    },
)

GTMETRIX_SAMPLE = {
    "page": "首页",
    "location": "Seattle, WA, USA；Chrome 142；Lighthouse 12.6.1；未限速",
    "metrics": "Performance 44%；Structure 78%；LCP 4.9s；TBT 316ms；CLS 0",
    "url": "https://gtmetrix.com/reports/jujubit.ai/XR8sJqBX/",
}


@dataclass(frozen=True)
class ProbePage:
    """一条站内 HTML 巡检结果，url 已归一化并可用于和 Pingdom 结果关联。"""

    url: str
    status: int | None
    ok: bool
    ttfb_ms: float | None
    method: str
    error: str


def _relative(path: Path) -> str:
    """报告中尽量展示相对仓库路径，便于读者定位输入数据。"""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _markdown_cell(value: object) -> str:
    """避免 URL 或 API 错误内容破坏 Markdown 表格。"""
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _markdown_link(label: str, url: str) -> str:
    """输出一个安全的 Markdown 链接；空 URL 统一显示为短横线。"""
    if not url:
        return "-"
    return f"[{_markdown_cell(label)}]({_markdown_cell(url)})"


def _number(value: object) -> float | None:
    """将 JSON 中可用的非负数指标转为 float，拒绝 -1、布尔值和 NaN。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
    elif isinstance(value, str):
        try:
            numeric = float(value)
        except ValueError:
            return None
    else:
        return None
    return numeric if math.isfinite(numeric) and numeric >= 0 else None


def _integer(value: object) -> int | None:
    numeric = _number(value)
    return int(numeric) if numeric is not None else None


def _percentile(values: Iterable[float], percent: float) -> float | None:
    """与巡检脚本一致地使用离散 P50/P95，避免小样本插值造成误读。"""
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percent))
    return ordered[index]


def _format_ms(value: float | None, decimals: int = 0) -> str:
    if value is None:
        return "-"
    return f"{value:.{decimals}f} ms"


def _format_bytes(value: object) -> str:
    numeric = _number(value)
    if numeric is None:
        return "-"
    units = ("B", "KiB", "MiB", "GiB")
    for unit in units:
        if numeric < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(numeric)} B"
            return f"{numeric:.1f} {unit}"
        numeric /= 1024
    return "-"


def _canonical_query(query: str) -> str:
    pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_QUERY_KEYS:
            continue
        if (key, value) not in pairs:
            pairs.append((key, value))
    return urlencode(sorted(pairs), doseq=True)


def normalize_internal_url(raw_url: str) -> str | None:
    """使用与巡检/Pingdom 脚本一致的规则归一化内部 HTML 页面 URL。"""
    try:
        parts = urlsplit(raw_url.strip())
    except ValueError:
        return None
    if (parts.hostname or "").lower() not in CANONICAL_HOSTS:
        return None
    if parts.scheme.lower() not in {"http", "https"}:
        return None

    path = parts.path or "/"
    collection_product = re.match(r"^/collections/[^/]+/products(/.*)$", path, re.IGNORECASE)
    if collection_product:
        path = "/products" + collection_product.group(1)
    if path != "/":
        path = "/" + path.strip("/")
    if ASSET_PATH_RE.search(path) or path.lower().startswith("/cdn/"):
        return None

    query = _canonical_query(parts.query)
    if path == "/pages/vip-program":
        query = ""
    return urlunsplit(("https", "jujubit.ai", path, query, ""))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 JSON：{path}（{exc}）") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 根节点不是对象：{path}")
    return payload


def find_probe_json() -> Path | None:
    """优先读取 2026-08-19 的正式巡检产物；不存在时才选择最新候选。"""
    preferred = ROOT / "artifacts/performance/2026-08-19/site-html-probe.json"
    if preferred.is_file():
        return preferred

    candidates = list((ROOT / "artifacts/performance").glob("**/site-html-probe.json"))
    candidates.extend((ROOT / "artifacts/performance").glob("jujubit-site-html-probe-*.json"))
    candidates = [candidate for candidate in candidates if candidate.is_file()]
    return max(candidates, key=lambda candidate: candidate.stat().st_mtime) if candidates else None


def _pingdom_candidate_score(path: Path) -> tuple[int, int, int, float]:
    """自动选择结果最完整、其次最新的 Pingdom JSON，避免优先拿到早期 1 页样本。"""
    try:
        payload = _read_json(path)
    except ValueError:
        return (-1, -1, -1, path.stat().st_mtime)
    results = payload.get("results")
    result_count = len(results) if isinstance(results, list) else 0
    processed = _integer(payload.get("processed_pages")) or result_count
    planned = _integer(payload.get("planned_pages")) or 0
    full_run = int(bool(planned and processed >= planned))
    return (full_run, processed, result_count, path.stat().st_mtime)


def find_pingdom_json() -> Path | None:
    """寻找已有 Pingdom checkpoint/最终 JSON；显式参数始终优先于此自动选择。"""
    base = ROOT / "artifacts/performance"
    candidates = [candidate for candidate in base.glob("**/pingdom-link-performance-*.json") if candidate.is_file()]
    return max(candidates, key=_pingdom_candidate_score) if candidates else None


def load_probe_pages(path: Path) -> tuple[list[ProbePage], dict[str, Any]]:
    payload = _read_json(path)
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raise ValueError(f"巡检 JSON 缺少 results 数组：{path}")

    pages: list[ProbePage] = []
    seen: set[str] = set()
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        # 429 保护性跳过项不是实际 HTML 页面响应，不能被当成失败页统计。
        if item.get("category") not in (None, "站内 HTML"):
            continue
        normalized = normalize_internal_url(str(item.get("url", "")))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        status = _integer(item.get("status"))
        ok = bool(item.get("ok")) and status is not None and 200 <= status < 400
        pages.append(
            ProbePage(
                url=normalized,
                status=status,
                ok=ok,
                ttfb_ms=_number(item.get("ttfb_ms")),
                method=str(item.get("method") or "-"),
                error=str(item.get("error") or ""),
            )
        )
    if not pages:
        raise ValueError(f"巡检 JSON 中没有可用的站内 HTML 页面：{path}")
    return pages, payload


def _pingdom_is_complete(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "")
    return status.startswith("完成") or (
        item.get("pingdom_status") == 3 and bool(item.get("report_url") or item.get("test_id"))
    )


def load_pingdom_results(path: Path | None) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None, str | None]:
    """载入 Pingdom JSON；文件未提供或尚不存在时返回空结果而非伪造失败。"""
    if path is None:
        return {}, None, None
    if not path.is_file():
        return {}, None, f"未找到 Pingdom JSON：`{_relative(path)}`"
    try:
        payload = _read_json(path)
    except ValueError as exc:
        return {}, None, str(exc)

    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return {}, payload, f"Pingdom JSON 缺少 results 数组：`{_relative(path)}`"

    by_url: dict[str, dict[str, Any]] = {}
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        normalized = normalize_internal_url(str(item.get("url") or ""))
        if not normalized:
            continue
        old = by_url.get(normalized)
        # 若 checkpoint 中意外出现同 URL 的多条记录，保留完成度更高的一条。
        if old is None or (_pingdom_is_complete(item) and not _pingdom_is_complete(old)):
            by_url[normalized] = item
    return by_url, payload, None


def page_identity(url: str) -> tuple[str, str]:
    """为 115 行明细生成简洁模块和页面标识，不猜测商品业务名称。"""
    parts = urlsplit(url)
    path = parts.path or "/"
    if path == "/":
        return "首页", "首页"
    if path == "/cart":
        return "购物车", "购物车"
    if path == "/collections":
        return "集合", "集合总览"
    if path.startswith("/collections/"):
        return "集合", f"集合：{unquote(path.removeprefix('/collections/'))}"
    if path.startswith("/products/"):
        product = unquote(path.removeprefix("/products/"))
        suffix = f"（variant={parts.query.split('=', 1)[1]}）" if parts.query.startswith("variant=") else ""
        return "商品", f"商品：{product}{suffix}"
    if path.startswith("/pages/"):
        return "内容页", f"页面：{unquote(path.removeprefix('/pages/'))}"
    if path == "/search":
        return "搜索", "搜索页"
    return "其他", path


def _pingdom_state(item: dict[str, Any] | None, unavailable_reason: str | None) -> tuple[str, str]:
    """将缺失、进行中、已完成和 API 错误区分开，避免把未跑误写为失败。"""
    if item is None:
        # 顶部会写明 JSON 缺失原因；逐行重复一长段文件错误会淹没页面明细。
        return ("未提供 Pingdom 结果" if unavailable_reason else "尚未收到 Pingdom 结果", "等待 Pingdom JSON")
    status = str(item.get("status") or "状态未知")
    error = str(item.get("error") or "")
    return status, error


def _pingdom_number(item: dict[str, Any] | None, key: str) -> float | None:
    return _number(item.get(key)) if item else None


def render_report(
    *,
    report_date: str,
    probe_path: Path,
    pages: list[ProbePage],
    probe_payload: dict[str, Any],
    pingdom_path: Path | None,
    pingdom_by_url: dict[str, dict[str, Any]],
    pingdom_payload: dict[str, Any] | None,
    pingdom_unavailable_reason: str | None,
) -> str:
    """将已读取的数据完整渲染为可提交 Markdown；不读取/写入任何外部服务。"""
    generated_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    pingdom_challenge_blocked = bool(
        pingdom_unavailable_reason
        and "Cloudflare" in pingdom_unavailable_reason
        and "Challenge" in pingdom_unavailable_reason
    )
    planned_pages = len(pages)
    probe_success = [page for page in pages if page.ok]
    ttfb_values = [page.ttfb_ms for page in probe_success if page.ttfb_ms is not None]
    p50 = _percentile(ttfb_values, 0.50)
    p95 = _percentile(ttfb_values, 0.95)
    average_ttfb = statistics.mean(ttfb_values) if ttfb_values else None
    slow_probe = sorted(
        (page for page in probe_success if page.ttfb_ms is not None),
        key=lambda page: page.ttfb_ms or -1,
        reverse=True,
    )[:5]

    matched_pingdom = {url: item for url, item in pingdom_by_url.items() if url in {page.url for page in pages}}
    pingdom_completed = [item for item in matched_pingdom.values() if _pingdom_is_complete(item)]
    pingdom_valid_load = [
        _pingdom_number(item, "load_time_ms")
        for item in pingdom_completed
        if _pingdom_number(item, "load_time_ms") is not None
    ]
    pingdom_valid_load = [value for value in pingdom_valid_load if value is not None]
    pingdom_grades = [
        _pingdom_number(item, "performance_grade")
        for item in pingdom_completed
        if _pingdom_number(item, "performance_grade") is not None
    ]
    pingdom_grades = [value for value in pingdom_grades if value is not None]
    pingdom_sizes = [
        _pingdom_number(item, "page_size_bytes")
        for item in pingdom_completed
        if _pingdom_number(item, "page_size_bytes") is not None
    ]
    pingdom_sizes = [value for value in pingdom_sizes if value is not None]
    pingdom_requests = [
        _pingdom_number(item, "requests")
        for item in pingdom_completed
        if _pingdom_number(item, "requests") is not None
    ]
    pingdom_requests = [value for value in pingdom_requests if value is not None]
    non_complete = [item for item in matched_pingdom.values() if not _pingdom_is_complete(item)]
    missing_pingdom = planned_pages - len(matched_pingdom)

    settings = pingdom_payload.get("settings", {}) if isinstance(pingdom_payload, dict) else {}
    region = settings.get("region") if isinstance(settings, dict) else None
    run_state = str(pingdom_payload.get("run_state") or "未提供") if pingdom_payload else "未提供"
    rate_limited = bool(pingdom_payload and pingdom_payload.get("rate_limited"))
    rate_limit_message = str(pingdom_payload.get("rate_limit_message") or "") if pingdom_payload else ""
    pingdom_source = _relative(pingdom_path) if pingdom_path and pingdom_path.is_file() else "-"
    extra_pingdom = set(pingdom_by_url) - {page.url for page in pages}

    pingdom_summary = (
        "- **Pingdom 美国节点合成测速**：本轮批量请求被 Cloudflare 机器人校验拦截，"
        "没有把拦截页指标当作全站页面性能结果。"
        if pingdom_challenge_blocked
        else (
            f"- **Pingdom 美国节点合成测速：{len(pingdom_completed)} / {planned_pages}** 个页面完成；"
            f"其中 **{len(pingdom_valid_load)} / {planned_pages}** 个页面取得有效加载时间。"
        )
    )

    lines = [
        f"# JuJuBit 网站性能测试报告（{report_date}）",
        "",
        f"> 生成时间：`{generated_at}`；数据源：[JuJuBit 站内及外部可跳转链接清单](JuJuBit-站内可跳转链接清单.md)。",
        "> 本报告严格区分当前执行环境的 HTTP 巡检、美国节点的合成测试，以及真实用户现场数据；**任何一项合成测试都不是美国真实用户加载时间**。",
        "",
        "## 0. 本轮范围与未纳入项",
        "",
        "| 清单目的地类型 | 数量 | 本轮处理 |",
        "|---|---:|---|",
        "| 固定目的地（源清单） | 191 | 作为链接范围来源；不等于 191 个独立网页。 |",
        f"| 归一化后的 `jujubit.ai` 站内 HTML 文档页 | {planned_pages} | **已进行全量低频 HTTP 巡检**；本报告的页面性能统计范围。 |",
        "| 站外 HTTP(S) 目的地 | 9 | 未作为 JuJuBit 网页测速；其页面性能由各运营方控制，不能混入本站指标。 |",
        "| `mailto:` 邮件操作 | 1 | 不产生网页加载，未测速。 |",
        "| 站内 CDN 图片媒体文件 | 5 | 不作为独立 HTML 页面测速；若代表页实际请求到它们，只反映在该代表页的整体结果中。 |",
        "",
        "> 归一化时会合并重复目的地、页面内锚点、集合上下文中的同一商品页和纯追踪参数；动态 Checkout、登录态页面及交互后才生成的地址不伪造成固定页面 URL。",
        "",
        "## 结论摘要",
        "",
        f"- **全量站内页面可达性：{len(probe_success)} / {planned_pages}** 个 HTML 文档页本次返回 2xx/3xx；这是低频 HTTP 巡检结果，不是完整页面加载测试。",
        pingdom_summary,
        "- **代表页实验室结果**显示，移动端首页、购物车、集合和创作页均存在可优化空间；创作页的 CLS 与交互阻塞尤其应优先复核。",
        "",
        "## 1. 全量站内 HTML 可达性与 HEAD 首响应等待（近似）",
        "",
        f"> 数据来源：`{_relative(probe_path)}`；采样时间：`{probe_payload.get('started_at', '-')}`；方法：`{probe_payload.get('method', 'HEAD then Range 0-0')}`。",
        "> 该巡检默认只读取响应头或极少量响应体，因此“近似 TTFB”是当前执行环境从发起 HEAD/Range 请求到收到首响应的等待，含网络、连接与服务端时间；**不包括图片、脚本、字体和完整页面渲染完成时间**。",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| 归一化站内 HTML 页面 | {planned_pages} |",
        f"| 2xx/3xx 可达 | {len(probe_success)} |",
        f"| 非 2xx/3xx / 请求异常 | {planned_pages - len(probe_success)} |",
        f"| HEAD 首响应等待平均值（近似） | {_format_ms(average_ttfb, 1)} |",
        f"| HEAD 首响应等待 P50（近似） | {_format_ms(p50, 1)} |",
        f"| HEAD 首响应等待 P95（近似） | {_format_ms(p95, 1)} |",
        "",
        "本次 HEAD 首响应等待（近似）最慢的 5 个可达页面：",
        "",
        "| 页面 | HTTP 状态 | HEAD 首响应等待（近似） | 方法 |",
        "|---|---:|---:|---|",
    ]
    for page in slow_probe:
        lines.append(
            f"| {_markdown_link(page.url, page.url)} | {page.status or '-'} | {_format_ms(page.ttfb_ms, 1)} | {_markdown_cell(page.method)} |"
        )

    lines.extend(
        [
            "",
            "## 2. 计划的 Pingdom 美国节点全量合成测速（本轮无有效页面结果）",
            "",
            "> Pingdom 的 `Load time`、请求数和页面大小来自固定机房的合成请求。它可用于比较同一测试条件下的页面差异，**不能表述为美国真实访客、真实用户 P75 或 Core Web Vitals**。",
            f"> Pingdom JSON：`{pingdom_source}`；任务状态：**{_markdown_cell(run_state)}**；节点：`{_markdown_cell(str(region or '未从 JSON 读取'))}`。默认脚本节点为美国东部 Washington D.C.（`us-east-1`）。",
            "",
            "| 指标 | 结果 |",
            "|---|---:|",
            f"| 计划页面 | {planned_pages} |",
            f"| 已收到页面结果条目 | {len(matched_pingdom)} / {planned_pages} |",
            f"| 完成测速 | {len(pingdom_completed)} / {planned_pages} |",
            f"| 有效 Load time | {len(pingdom_valid_load)} / {planned_pages} |",
            f"| 已收到但未完成 / API 异常 / 429 保护 | {len(non_complete)} / {planned_pages} |",
            f"| 尚未写入 Pingdom 结果 | {missing_pingdom} / {planned_pages} |",
            f"| Load time P50（仅有效结果） | {_format_ms(_percentile(pingdom_valid_load, 0.50), 0)} |",
            f"| Load time P95（仅有效结果） | {_format_ms(_percentile(pingdom_valid_load, 0.95), 0)} |",
            f"| 平均 YSlow 等级（仅已返回等级） | {f'{statistics.mean(pingdom_grades):.1f}' if pingdom_grades else '-'} |",
            f"| 平均页面大小（仅已返回大小） | {_format_bytes(statistics.mean(pingdom_sizes)) if pingdom_sizes else '-'} |",
            f"| 平均请求数（仅已返回请求数） | {f'{statistics.mean(pingdom_requests):.1f}' if pingdom_requests else '-'} |",
            "",
        ]
    )
    if pingdom_unavailable_reason:
        is_challenge_blocked = "Cloudflare" in pingdom_unavailable_reason and "Challenge" in pingdom_unavailable_reason
        pending_message = (
            "以下 115 行保留为待填充状态；如需美国机房全量合成数据，应先让站点对已授权的"
            "监测来源放行，再以相同口径复跑。"
            if is_challenge_blocked
            else "以下 115 行保留为待填充状态；全量任务结束后，指定 `--pingdom-json` 重新生成即可写入每页报告链接。"
        )
        lines.extend(
            [
                f"> **Pingdom 批量结果不可用**：{pingdom_unavailable_reason.rstrip('。')}。{pending_message}",
                "",
            ]
        )
    elif len(pingdom_completed) < planned_pages:
        lines.extend(
            [
                f"> **Pingdom 尚未全量完成**：当前仅 `{len(pingdom_completed)} / {planned_pages}` 完成测速。未完成页面不能被解释为慢、失败或通过；待完整 JSON 产出后需重新生成本报告。",
                "",
            ]
        )
    elif len(pingdom_valid_load) < planned_pages:
        lines.extend(
            [
                f"> Pingdom 已处理全量页面，但仅 `{len(pingdom_valid_load)} / {planned_pages}` 返回有效 `Load time`；缺失或为 `-1` 的值没有计入统计。",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "> 已在下方逐页写入本次 Pingdom 结果和可点击报告链接；报告阅读不依赖本地 artifacts 文件。",
                "",
            ]
        )
    if rate_limited:
        lines.extend(
            [
                f"> 429 限流保护已触发：{_markdown_cell(rate_limit_message or 'Pingdom API 限流后已停止后续请求。')}",
                "",
            ]
        )
    if extra_pingdom:
        lines.extend(
            [
                f"> 注：Pingdom JSON 中有 {len(extra_pingdom)} 条未匹配本次 115 页归一化清单的结果，未纳入上方汇总。",
                "",
            ]
        )

    lines.extend(
        [
            "## 3. PageSpeed Insights 移动端代表页",
            "",
            "> CrUX 是 Chrome 真实用户的近 28 天聚合现场数据；PSI 标准页面不能据此限定为美国用户。Lighthouse 是固定设备/网络条件下的实验室结果，也不是美国真实用户数据。外链再次打开时可能显示更新后的实时报告。",
            "",
            "| 页面 | CrUX 现场数据 | Lighthouse 移动端实验室数据 | 报告 |",
            "|---|---|---|---|",
        ]
    )
    for sample in PSI_SAMPLES:
        lines.append(
            "| "
            + " | ".join(
                [
                    sample["page"],
                    sample["crux"],
                    sample["lab"],
                    _markdown_link("打开 PSI 报告", sample["url"]),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## 4. GTmetrix 美国西部代表页",
            "",
            "> 以下为美国西部 Seattle 节点的单次合成测试。GTmetrix Guest 报告有留存期限，若链接失效需从工具页面重新生成；其分数不可与 PSI 分数相加或换算。",
            "",
            "| 页面 | 测试条件 | 指标 | 报告 |",
            "|---|---|---|---|",
            "| "
            + " | ".join(
                [
                    GTMETRIX_SAMPLE["page"],
                    GTMETRIX_SAMPLE["location"],
                    GTMETRIX_SAMPLE["metrics"],
                    _markdown_link("打开 GTmetrix 报告", GTMETRIX_SAMPLE["url"]),
                ]
            )
            + " |",
            "",
            "## 5. 工具实际执行状态",
            "",
            "| 工具/方法 | 本轮范围 | 状态 | 说明 |",
            "|---|---|---|---|",
            f"| 低频 HTTP HEAD/Range 巡检 | {planned_pages} 个站内 HTML 页面 | 已完成 | 115 页逐页状态与 HEAD 首响应等待见第 1、7 节；不是完整浏览器加载。 |",
            "| Pingdom（美国东部） | 计划 115 页 | 无有效结果 | PingdomPageSpeed/pingbot 被 Cloudflare 429 Challenge 拦截；HAR 已复核，拦截页数值已排除。 |",
            "| PageSpeed Insights / CrUX | 5 个移动端代表页 | 已取得代表页记录 | 标准 PSI 不能按美国筛选；公开 API 本轮额度为 0，未对 115 页批量请求。 |",
            "| GTmetrix（Seattle） | 首页 | 已取得单页记录 | 可用于美国西部合成参考；Guest 报告有留存期限。 |",
            "| WebPageTest | 计划美国节点代表页 | 未取得有效结果 | 本轮免费运行额度已耗尽；不绕过其额度限制。 |",
            "| SpeedVitals / DebugBear / SpeedCurve | 全站定时或多地域 | 未运行 | 需要相应账号、套餐或项目接入；不应把未授权服务写成已测。 |",
            "| 美国真实用户 RUM | 全站真实用户 | 尚未接入 | 只有按 `country=US` 采集的 RUM P75/P90 才能表述为美国用户实际体验。 |",
            "",
            "## 6. 优先关注项",
            "",
            "1. **创作页**：PSI 记录的 CLS（现场 0.61、实验室 0.73）和 TBT（1070ms）偏高，应先检查首屏容器尺寸、异步组件插入和主线程长任务。",
            "2. **移动端 LCP**：PSI 中首页、购物车、集合、创作和模板集合页的实验室 LCP 都高于 2.5s 参考目标。应通过瀑布图定位实际 LCP 元素，再检查首屏图片尺寸/格式、懒加载、字体和第三方脚本。",
            "3. **美国用户口径**：本轮 Pingdom 批量已被 Cloudflare Challenge 拦截，不能用于美国节点结论；现有 GTmetrix 首页美国西部结果仅作代表页参考。若要得出“美国用户使用时间”，需接入 RUM，并按 `country=US`、设备和页面类型输出 LCP/INP/CLS 的 P75/P90。",
            "",
            "## 7. 115 页待复跑明细（HTTP 巡检已完成；Pingdom 无有效结果）",
            "",
            "> 共列出 **115 个** 归一化站内 HTML 页面。`HTTP 巡检` 与 `HEAD 首响应等待（近似）` 来自本轮已完成的全量低频巡检；当前没有把被 Cloudflare Challenge 拦截的 Pingdom 批量数值写入表格。未完成或缺失的 Pingdom 状态不会被误写为性能失败。",
            "",
            "| # | 模块 | 页面 | HTTP 巡检 | HEAD 首响应等待（近似） | Pingdom 状态 | Load time | 等级 | 请求数 | 页面大小 | Pingdom 报告 | 说明 |",
            "|---:|---|---|---|---:|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for index, page in enumerate(pages, start=1):
        result = pingdom_by_url.get(page.url)
        module, name = page_identity(page.url)
        state, note = _pingdom_state(result, pingdom_unavailable_reason)
        load_time = _pingdom_number(result, "load_time_ms")
        grade = _pingdom_number(result, "performance_grade")
        requests = _pingdom_number(result, "requests")
        page_size = result.get("page_size_bytes") if result else None
        report_url = str(result.get("report_url") or "") if result else ""
        if result and not note and _pingdom_is_complete(result) and load_time is None:
            note = "测试完成，但 API 未返回有效 Load time（未纳入汇总）。"
        elif result and not note and _pingdom_is_complete(result):
            note = f"轮询 {result.get('poll_count', '-')} 次"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    _markdown_cell(module),
                    _markdown_link(name, page.url),
                    _markdown_cell(f"{page.status if page.status is not None else '-'}（{'通过' if page.ok else '异常'}）"),
                    _format_ms(page.ttfb_ms, 1),
                    _markdown_cell(state),
                    _format_ms(load_time, 0),
                    f"{grade:.0f}" if grade is not None else "-",
                    f"{requests:.0f}" if requests is not None else "-",
                    _format_bytes(page_size),
                    _markdown_link("打开报告", report_url),
                    _markdown_cell(note or "-"),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## 8. 在 Cloudflare 放行后复跑 Pingdom 的方式",
            "",
            "请先让站点对获授权的测速来源放行；随后让低频 Pingdom 全量任务写完 JSON，再由本脚本生成可提交报告：",
            "",
            "```bash",
            "python3 scripts/generate_website_performance_report.py \\",
            "  --pingdom-json artifacts/performance/pingdom-link-performance-<时间戳>.json \\",
            f"  --output docs/JuJuBit-网站性能测试报告-{report_date}.md",
            "```",
            "",
            "本脚本本身不运行外部测速；它只将已有 JSON 转写为 Markdown。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="从已有 JSON 生成 JuJuBit 中文网站性能测试报告")
    parser.add_argument(
        "--probe-json",
        type=Path,
        default=None,
        help="站内 HTML 巡检 JSON；默认优先 artifacts/performance/2026-08-19/site-html-probe.json",
    )
    parser.add_argument(
        "--pingdom-json",
        type=Path,
        default=None,
        help="可选的 Pingdom JSON；省略时自动选择最完整的已有结果，指定但不存在时生成待填充报告",
    )
    parser.add_argument("--date", default=DEFAULT_DATE, help="报告标题和默认文件名日期，默认 2026-08-19")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="输出 Markdown；默认 docs/JuJuBit-网站性能测试报告-<date>.md",
    )
    parser.add_argument(
        "--pingdom-challenge-blocked",
        action="store_true",
        help="本轮 Pingdom 批量已确认遭 Cloudflare Challenge 拦截；在报告中明确排除该批次指标",
    )
    args = parser.parse_args()

    probe_path = args.probe_json or find_probe_json()
    if probe_path is None or not probe_path.is_file():
        parser.error("未找到 site HTML probe JSON；请用 --probe-json 指定有效文件")
    try:
        pages, probe_payload = load_probe_pages(probe_path)
    except ValueError as exc:
        parser.error(str(exc))

    pingdom_path = args.pingdom_json if args.pingdom_json is not None else find_pingdom_json()
    pingdom_by_url, pingdom_payload, pingdom_unavailable_reason = load_pingdom_results(pingdom_path)
    if args.pingdom_challenge_blocked:
        # 已验证为 Cloudflare Challenge 的测试不能与真实页面性能数据混用。保留
        # 默认 115 页明细的待填充状态，而不是让旧 checkpoint 的错误低耗时进入报告。
        pingdom_by_url = {}
        pingdom_payload = None
        pingdom_path = None
        pingdom_unavailable_reason = (
            "本轮 PingdomPageSpeed/pingbot 被 Cloudflare 429 Challenge 拦截；"
            "HAR 已确认主文档带 `cf-mitigated: challenge`，批量指标已排除。"
        )
    output = args.output or ROOT / "docs" / f"JuJuBit-网站性能测试报告-{args.date}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_report(
            report_date=args.date,
            probe_path=probe_path,
            pages=pages,
            probe_payload=probe_payload,
            pingdom_path=pingdom_path,
            pingdom_by_url=pingdom_by_url,
            pingdom_payload=pingdom_payload,
            pingdom_unavailable_reason=pingdom_unavailable_reason,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report": str(output),
                "html_pages": len(pages),
                "pingdom_result_entries": len(pingdom_by_url),
                "pingdom_source": str(pingdom_path) if pingdom_path else None,
                "pingdom_warning": pingdom_unavailable_reason,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
