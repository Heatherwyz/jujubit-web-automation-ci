#!/usr/bin/env python3
"""用 Pingdom 的匿名接口低频测试 JuJuBit 链接清单中的站内 HTML 页面。

脚本只向 Pingdom 提交公开的 JuJuBit 页面 URL，不上传 Cookie、登录态、表单数据或
本地文件。每次 API 请求都复用同一匿名会话，并默认至少间隔 3 秒、串行执行；这既
避免把它当成压测工具，也降低触发 Pingdom 或 Shopify 限流的概率。

Pingdom 的公开页面结果链接格式为 ``https://tools.pingdom.com/#<test_id>``。该链接
由报告逐条输出，便于在浏览器中查看瀑布图和具体资源。匿名接口的额度及留存策略可能
会变化，因此脚本在 HTTP 429 时会指数退避后停止剩余任务，而不会继续加大请求量。
"""

from __future__ import annotations

import argparse
import datetime as dt
import http.cookiejar
import json
import math
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


PINGDOM_BASE_URL = "https://tools.pingdom.com"
PINGDOM_US_EAST_REGION = "us-east-1"
PINGDOM_US_EAST_NAME = "North America - USA - Washington D.C."
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

# JuJuBit 的正常页面通常会加载数十到数百项资源。匿名 Pingdom 任务若只得到
# 3 个左右请求、约 100 KB 的页面，常见原因是 Cloudflare 验证页而非真实站点。
# 只有落入这两个很窄的异常形态时，才额外读取一次 HAR 作复核，避免给正常页面
# 增加任何 API 请求。
SUSPICIOUS_REQUESTS_AT_MOST = 3
VERY_LOW_REQUESTS_AT_MOST = 10
SMALL_PAGE_BYTES_AT_MOST = 512 * 1024

T = TypeVar("T")


class PingdomHttpError(RuntimeError):
    """保留 Pingdom API 的 HTTP 状态和响应头，供 429 保护逻辑使用。"""

    def __init__(self, status: int, message: str, headers: Any | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.headers = headers


@dataclass
class PageResult:
    """一个归一化站内页面在 Pingdom 中的一次合成测速结果。"""

    url: str
    status: str = "未开始"
    test_id: str = ""
    report_url: str = ""
    started_at: str = ""
    completed_at: str = ""
    pingdom_status: int | None = None
    load_time_ms: int | None = None
    performance_grade: int | None = None
    requests: int | None = None
    page_size_bytes: int | None = None
    raw_metrics: dict[str, Any] = field(default_factory=dict)
    har_document_evidence: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    poll_count: int = 0


def _canonical_query(query: str) -> str:
    """保留功能参数，去掉追踪参数，并合并重复的同名同值参数。"""
    pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_QUERY_KEYS:
            continue
        if (key, value) not in pairs:
            pairs.append((key, value))
    return urlencode(sorted(pairs), doseq=True)


def normalize_internal_url(raw_url: str) -> str | None:
    """将清单 URL 归一化为唯一的 JuJuBit HTML 页面目标。

    规则与站内 HTML 轻量巡检脚本保持等价：忽略锚点、统一 collection 中的商品
    路径、过滤站内静态资源，并将会员页的返回来源参数合并成同一个页面样本。
    """
    try:
        parts = urlsplit(raw_url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if host not in CANONICAL_HOSTS or parts.scheme.lower() not in {"http", "https"}:
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
    return urlunsplit(("https", CANONICAL_HOST, path, query, ""))


def load_internal_html_urls(path: Path) -> tuple[list[str], dict[str, int]]:
    """从链接清单读取、归一化并去重站内 HTML 页面。"""
    raw_urls = LINK_RE.findall(path.read_text(encoding="utf-8"))
    urls: list[str] = []
    seen: set[str] = set()
    skipped = {"站外/非 HTTP": 0, "站内媒体或非 HTML": 0, "无效 URL": 0}
    for raw_url in raw_urls:
        try:
            parts = urlsplit(raw_url.strip())
        except ValueError:
            skipped["无效 URL"] += 1
            continue
        host = (parts.hostname or "").lower()
        if host not in CANONICAL_HOSTS:
            skipped["站外/非 HTTP"] += 1
            continue
        normalized = normalize_internal_url(raw_url)
        if normalized is None:
            skipped["站内媒体或非 HTML"] += 1
            continue
        if normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)
    return urls, skipped


def _json_message(body: bytes) -> str:
    """尽可能从 API JSON 中取出可读的错误信息，避免把 HTML 错页直接写进报告。"""
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return "Pingdom API 返回空响应"
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text[:400]
    if isinstance(data, dict):
        for key in ("message", "error", "description"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict):
                return json.dumps(value, ensure_ascii=False)[:400]
    return json.dumps(data, ensure_ascii=False)[:400]


def _retry_after_seconds(headers: Any | None) -> float | None:
    """读取 Retry-After；既支持秒数，也支持 HTTP 日期。"""
    if headers is None:
        return None
    value = headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=dt.timezone.utc)
            return max(0.0, (retry_at - dt.datetime.now(dt.timezone.utc)).total_seconds())
        except (TypeError, ValueError, IndexError, OverflowError):
            return None


class PingdomAnonymousClient:
    """带匿名 Cookie 会话、请求节流和 429 保护的 Pingdom API 客户端。"""

    def __init__(
        self,
        request_interval: float,
        timeout: float,
        max_rate_limit_retries: int,
        rate_limit_backoff: float,
        max_rate_limit_backoff: float,
    ) -> None:
        self.request_interval = request_interval
        self.timeout = timeout
        self.max_rate_limit_retries = max_rate_limit_retries
        self.rate_limit_backoff = rate_limit_backoff
        self.max_rate_limit_backoff = max_rate_limit_backoff
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookie_jar))
        self.next_request_at = 0.0
        self.rate_limited = False
        self.rate_limit_message = ""
        self.rate_limit_retries_used = 0

    def _wait_for_request_slot(self) -> None:
        wait_seconds = self.next_request_at - time.monotonic()
        if wait_seconds > 0:
            time.sleep(wait_seconds)

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """执行一次 API 请求；调用者负责按 429 规则决定是否重试。"""
        self._wait_for_request_slot()
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {
            "Accept": "application/json",
            "User-Agent": "JuJuBit-pingdom-link-performance/1.0 (low-rate synthetic audit)",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{PINGDOM_BASE_URL}{path}",
            data=body,
            method=method,
            headers=headers,
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                response_body = response.read()
        except HTTPError as exc:
            response_body = exc.read()
            raise PingdomHttpError(exc.code, _json_message(response_body), exc.headers) from exc
        except URLError as exc:
            raise PingdomHttpError(0, f"网络错误：{getattr(exc, 'reason', exc)}") from exc
        except (TimeoutError, OSError) as exc:
            # urllib 有时会将读取超时直接抛为 socket.timeout，而不是 URLError。
            # 把单个 API 网络错误落到当前页面结果，不能让全量任务中断且不产出报告。
            raise PingdomHttpError(0, f"网络超时或连接错误：{exc}") from exc
        finally:
            # 无论成功或失败，都给 Pingdom 的匿名接口留下最小间隔。
            self.next_request_at = time.monotonic() + self.request_interval

        try:
            payload_data = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PingdomHttpError(0, f"Pingdom API 返回非 JSON 响应：{exc}") from exc
        if not isinstance(payload_data, dict):
            raise PingdomHttpError(0, "Pingdom API 返回了非对象 JSON")
        return payload_data

    def request_with_rate_limit(self, request: Callable[[], T]) -> T:
        """遇到 429 时按指数退避重试；超过次数后标记全局停止。"""
        retries = 0
        while True:
            try:
                return request()
            except PingdomHttpError as exc:
                if exc.status != 429:
                    raise
                if retries >= self.max_rate_limit_retries:
                    self.rate_limited = True
                    self.rate_limit_message = (
                        f"Pingdom API 连续返回 HTTP 429，已在 {retries} 次指数退避后停止后续页面测试。"
                    )
                    raise PingdomHttpError(429, self.rate_limit_message, exc.headers) from exc
                retry_after = _retry_after_seconds(exc.headers)
                exponential_wait = min(
                    self.max_rate_limit_backoff,
                    self.rate_limit_backoff * (2**retries),
                )
                wait_seconds = min(self.max_rate_limit_backoff, max(exponential_wait, retry_after or 0.0))
                self.rate_limit_retries_used += 1
                retries += 1
                time.sleep(wait_seconds)

    def create_test(self, url: str, region: str) -> dict[str, Any]:
        return self.request_with_rate_limit(
            lambda: self._request_json("POST", "/v1/tests/create", {"url": url, "region": region})
        )

    def get_test(self, test_id: str) -> dict[str, Any]:
        return self.request_with_rate_limit(lambda: self._request_json("GET", f"/v1/tests/{test_id}"))

    def get_metrics(self, test_id: str) -> dict[str, Any]:
        return self.request_with_rate_limit(lambda: self._request_json("GET", f"/v1/tests/{test_id}/metrics"))

    def get_har(self, test_id: str) -> dict[str, Any]:
        """仅供疑似被拦截的异常 metrics 复核 document 响应。"""
        return self.request_with_rate_limit(lambda: self._request_json("GET", f"/v1/tests/{test_id}/har"))


def _metric_value(metrics: dict[str, Any], name: str) -> int | None:
    value = metrics.get(name)
    if not isinstance(value, dict):
        return None
    current = value.get("current")
    if isinstance(current, bool):
        return None
    if isinstance(current, (int, float)) and current >= 0:
        # Pingdom 偶尔会把尚不可用的时间写成 -1；这不是「-1ms 加载完成」，
        # 不能参与 P50/P95 或作为有效性能指标展示。
        return int(current)
    return None


def _metrics_look_like_interception(metrics: dict[str, Any]) -> bool:
    """判断是否值得额外读取一次 HAR，而非把所有已完成页面都读一遍。"""
    request_count = _metric_value(metrics, "request")
    page_size_bytes = _metric_value(metrics, "size")
    if request_count is None:
        return False
    return request_count <= SUSPICIOUS_REQUESTS_AT_MOST or (
        request_count <= VERY_LOW_REQUESTS_AT_MOST
        and page_size_bytes is not None
        and page_size_bytes <= SMALL_PAGE_BYTES_AT_MOST
    )


def _normalized_har_headers(headers: object) -> dict[str, str]:
    """将 HAR 的 header 数组归一化，供大小写不敏感地判断 Cloudflare 标记。"""
    normalized: dict[str, str] = {}
    if not isinstance(headers, list):
        return normalized
    for item in headers:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        key = name.lower()
        # HAR 通常没有同名响应头；若有则保留全部值，避免漏掉 cf-mitigated。
        normalized[key] = f"{normalized[key]}, {value}" if key in normalized else value
    return normalized


def _har_document_evidence(har: dict[str, Any]) -> list[dict[str, Any]]:
    """摘出 HAR 中 document 请求的状态与响应头，不保存整份可能很大的 HAR。"""
    log = har.get("log")
    entries = log.get("entries") if isinstance(log, dict) else None
    if not isinstance(entries, list):
        return []

    documents: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        content = response.get("content")
        content = content if isinstance(content, dict) else {}
        resource_type = (
            content.get("_resourceType")
            or response.get("_resourceType")
            or entry.get("_resourceType")
            or entry.get("resourceType")
        )
        raw_status = response.get("status")
        status: int | None
        if isinstance(raw_status, bool):
            status = None
        elif isinstance(raw_status, int):
            status = raw_status
        elif isinstance(raw_status, str) and raw_status.isdigit():
            status = int(raw_status)
        else:
            status = None
        request = entry.get("request")
        request_url = request.get("url") if isinstance(request, dict) else ""
        page_ref = entry.get("pageref")

        # Pingdom 返回的 HAR 并不总是包含 ``_resourceType: document``。在实际
        # Cloudflare Challenge 样本中，主文档使用的是 ``pageref == request.url``。
        # 该条件是对 Pingdom HAR 的可靠回退，避免因缺少私有字段而漏掉 429 验证页。
        is_document = isinstance(resource_type, str) and resource_type.lower() == "document"
        is_page_document = (
            isinstance(request_url, str)
            and isinstance(page_ref, str)
            and request_url == page_ref
        )
        if not is_document and not is_page_document:
            continue
        documents.append(
            {
                "url": request_url if isinstance(request_url, str) else "",
                "status": status,
                "headers": _normalized_har_headers(response.get("headers")),
            }
        )
    return documents


def _cloudflare_interception_reason(documents: list[dict[str, Any]]) -> str | None:
    """从 document 响应判断指标是否实际来自 Cloudflare 验证页。"""
    for document in documents:
        status = document.get("status")
        headers = document.get("headers")
        headers = headers if isinstance(headers, dict) else {}
        mitigated = headers.get("cf-mitigated")
        if isinstance(mitigated, str) and "challenge" in mitigated.lower():
            status_text = f"HTTP {status}" if isinstance(status, int) else "未知 HTTP 状态"
            return (
                f"Pingdom HAR 的 document 请求返回 {status_text}，且响应头包含 "
                "`cf-mitigated: challenge`；本次测到的是 Cloudflare 验证页而非真实页面，"
                "原始 metrics 已保留在 JSON 中，但不会计入性能统计。"
            )
        if isinstance(status, int) and not 200 <= status < 400:
            return (
                f"Pingdom HAR 的 document 请求返回 HTTP {status}（非 2xx/3xx）；"
                "本次并非真实页面加载，原始 metrics 已保留在 JSON 中，但不会计入性能统计。"
            )
    return None


def run_test(
    client: PingdomAnonymousClient,
    url: str,
    region: str,
    poll_interval: float,
    poll_timeout: float,
) -> PageResult:
    """提交一个页面、轮询完成状态并读取 metrics。"""
    result = PageResult(url=url, status="进行中", started_at=dt.datetime.now().astimezone().isoformat(timespec="seconds"))
    try:
        created = client.create_test(url, region)
        test_id = str(created.get("id", ""))
        if not test_id:
            result.status = "提交失败"
            result.error = f"Pingdom 未返回测试 ID：{json.dumps(created, ensure_ascii=False)[:300]}"
            return result
        result.test_id = test_id
        result.report_url = f"{PINGDOM_BASE_URL}/#{test_id}"
        result.pingdom_status = created.get("status") if isinstance(created.get("status"), int) else None

        deadline = time.monotonic() + poll_timeout
        while time.monotonic() < deadline:
            if poll_interval:
                time.sleep(poll_interval)
            status_data = client.get_test(test_id)
            result.poll_count += 1
            status = status_data.get("status")
            result.pingdom_status = status if isinstance(status, int) else result.pingdom_status
            if status == 3 or isinstance(status_data.get("resources"), dict):
                metrics = client.get_metrics(test_id)
                result.raw_metrics = metrics
                result.load_time_ms = _metric_value(metrics, "load_time")
                result.performance_grade = _metric_value(metrics, "yslow_score")
                result.requests = _metric_value(metrics, "request")
                result.page_size_bytes = _metric_value(metrics, "size")
                if _metrics_look_like_interception(metrics):
                    # 只有极低资源数/体积的异常结果才读取一次 HAR。正常页面不会多一次
                    # Pingdom API 请求；HAR 本身不写入报告 JSON，避免无意义地放大产物。
                    try:
                        har = client.get_har(test_id)
                    except PingdomHttpError as exc:
                        # HAR 只是复核证据。它暂时不可读不能反过来否定已经完成的测速，
                        # 也不能让单页的可选复核把整个任务标成 API 失败。
                        result.error = (
                            "本次 metrics 的请求数/页面体积异常低，已尝试读取 HAR 复核是否为拦截页；"
                            f"但 HAR 暂不可读（HTTP {exc.status}: {exc}）。请通过 Pingdom 报告人工复核。"
                        )
                    else:
                        result.har_document_evidence = _har_document_evidence(har)
                        interception_reason = _cloudflare_interception_reason(result.har_document_evidence)
                        if interception_reason:
                            # 仍是 Pingdom 已完成的任务，不应被归为测试失败；只是它没有拿到
                            # 真实页面的性能数据。保留 raw_metrics 和公开报告链接帮助复核。
                            result.status = "完成（Cloudflare 拦截，指标无效）"
                            result.load_time_ms = None
                            result.performance_grade = None
                            result.requests = None
                            result.page_size_bytes = None
                            result.error = interception_reason
                            result.completed_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
                            return result
                if result.load_time_ms is None:
                    result.status = "完成（指标不完整）"
                    result.error = (
                        "Pingdom 已生成报告，但本次 API 返回的 load_time 无效（通常为 -1）；"
                        "该链接可用于复核瀑布图，加载时间应稍后重跑确认。"
                    )
                else:
                    result.status = "完成"
                result.completed_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
                return result
            # Pingdom 已有明确结束时间但没有 metrics 时，不继续无效轮询。
            if status_data.get("timeCompleted"):
                result.status = "测试失败"
                result.error = f"Pingdom 测试已结束，但没有可读取的 metrics（status={status!r}）。"
                result.completed_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
                return result

        result.status = "轮询超时"
        result.error = f"在 {poll_timeout:g} 秒内未等到 Pingdom metrics。"
        result.completed_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        return result
    except PingdomHttpError as exc:
        result.status = "限流停止" if exc.status == 429 and client.rate_limited else "API 错误"
        result.error = f"HTTP {exc.status}: {exc}" if exc.status else str(exc)
        result.completed_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        return result


def _percentile(values: Iterable[int], percentile: float) -> int | None:
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1)
    return ordered[index]


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "-"
    units = ("B", "KB", "MB", "GB")
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def build_markdown_report(
    results: list[PageResult],
    inventory: Path,
    started_at: str,
    finished_at: str,
    settings: dict[str, Any],
    skipped_sources: dict[str, int],
    rate_limited: bool,
    rate_limit_message: str,
    planned_pages: int | None = None,
    run_state: str = "已完成",
) -> str:
    completed = [item for item in results if item.status.startswith("完成")]
    cloudflare_invalid = [item for item in completed if item.status == "完成（Cloudflare 拦截，指标无效）"]
    complete_metrics = [item for item in completed if item.load_time_ms is not None]
    incomplete_metrics = [
        item
        for item in completed
        if item.load_time_ms is None and item.status != "完成（Cloudflare 拦截，指标无效）"
    ]
    failures = [
        item
        for item in results
        if not item.status.startswith("完成") and item.status != "跳过（429 保护）"
    ]
    protected_skips = [item for item in results if item.status == "跳过（429 保护）"]
    load_times = [item.load_time_ms for item in complete_metrics if item.load_time_ms is not None]
    grades = [item.performance_grade for item in completed if item.performance_grade is not None]
    page_sizes = [item.page_size_bytes for item in completed if item.page_size_bytes is not None]
    request_counts = [item.requests for item in completed if item.requests is not None]
    date = started_at[:10]
    planned_count = planned_pages if planned_pages is not None else len(results)
    checkpoint_note = (
        "> 这是运行中的增量 checkpoint；每完成一个页面便会原子更新一次，最终完成后会覆盖为最终报告。"
        if run_state != "已完成"
        else "> 这是最终报告；每条页面结果均已写入对应的 JSON 明细。"
    )

    lines = [
        f"# JuJuBit 美国东部 Pingdom 性能测试报告（{date}）",
        "",
        f"> 运行状态：**{run_state}**；开始：`{started_at}`；最近写入：`{finished_at}`；数据源：`{inventory}`。",
        f"> 测试节点：`{settings['region']}`（{PINGDOM_US_EAST_NAME}）；工具：Pingdom 匿名 API；执行方式：串行（并发 1）。",
        "> 本报告的加载时间、请求数和页面大小来自 Pingdom 美国东部合成测试，不能等同于美国真实用户 RUM 或 Core Web Vitals 的 P75。",
        checkpoint_note,
        "",
        "## 测试配置",
        "",
        f"- API 请求最小间隔：`{settings['request_interval_seconds']:g}s`（每个请求均受此节流保护）。",
        f"- 状态轮询间隔：`{settings['poll_interval_seconds']:g}s`；单页轮询超时：`{settings['poll_timeout_seconds']:g}s`；网络超时：`{settings['timeout_seconds']:g}s`。",
        f"- HTTP 429 处理：最多指数退避 `{settings['max_rate_limit_retries']}` 次，初始等待 `{settings['rate_limit_backoff_seconds']:g}s`，最大等待 `{settings['max_rate_limit_backoff_seconds']:g}s`，耗尽后停止剩余页面。",
        "- 归一化规则：移除锚点与追踪参数；集合页中的商品路径归为 `/products/<handle>`；站内静态资源和站外链接不提交到 Pingdom。",
        "",
        "## 汇总",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| 计划页面 | {planned_count} |",
        f"| 已处理页面 | {len(results)} |",
        f"| 完成测速 | {len(completed)} |",
        f"| 完成但指标无效（Cloudflare 拦截） | {len(cloudflare_invalid)} |",
        f"| 完成但加载时间不可用 | {len(incomplete_metrics)} |",
        f"| API/测试异常 | {len(failures)} |",
        f"| 429 保护性跳过 | {len(protected_skips)} |",
        f"| 加载时间 P50 | {(_percentile(load_times, 0.50) if load_times else '-')} ms |",
        f"| 加载时间 P95 | {(_percentile(load_times, 0.95) if load_times else '-')} ms |",
        f"| 平均性能等级 | {(round(sum(grades) / len(grades), 1) if grades else '-')} |",
        f"| 平均页面大小 | {_format_bytes(round(sum(page_sizes) / len(page_sizes)) if page_sizes else None)} |",
        f"| 平均请求数 | {(round(sum(request_counts) / len(request_counts), 1) if request_counts else '-')} |",
        "",
        "## 清单处理",
        "",
        "| 未提交到 Pingdom 的来源项 | 数量 |",
        "|---|---:|",
        f"| 站外/非 HTTP | {skipped_sources.get('站外/非 HTTP', 0)} |",
        f"| 站内媒体或非 HTML | {skipped_sources.get('站内媒体或非 HTML', 0)} |",
        f"| 无效 URL | {skipped_sources.get('无效 URL', 0)} |",
        "",
    ]
    if rate_limited:
        lines.extend(["## 限流保护", "", f"- **已停止后续请求**：{rate_limit_message}", ""])

    lines.extend(
        [
            "## 页面结果",
            "",
            "| 页面 | 状态 | 加载时间(ms) | 等级 | 请求数 | 页面大小 | Pingdom 报告 | 说明 |",
            "|---|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for item in results:
        page = f"[{_markdown_cell(item.url)}]({_markdown_cell(item.url)})"
        report = f"[打开报告]({_markdown_cell(item.report_url)})" if item.report_url else "-"
        note = item.error or (f"轮询 {item.poll_count} 次" if item.status == "完成" else "-")
        lines.append(
            "| "
            + " | ".join(
                [
                    page,
                    _markdown_cell(item.status),
                    str(item.load_time_ms) if item.load_time_ms is not None else "-",
                    str(item.performance_grade) if item.performance_grade is not None else "-",
                    str(item.requests) if item.requests is not None else "-",
                    _format_bytes(item.page_size_bytes),
                    report,
                    _markdown_cell(note),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 结果解读",
            "",
            "- `加载时间`是 Pingdom 完成本次页面资源请求所记录的合成测试时间；它不是 LCP，也不能替代真实用户的 INP、CLS。",
            "- `完成（Cloudflare 拦截，指标无效）`表示 Pingdom 任务本身已结束，但异常低的 metrics 经 HAR 复核后确认 document 是 Cloudflare 验证页；该行仍保留原始 metrics（JSON）和 Pingdom 报告链接，但不会计入任何性能统计。",
            "- `等级`为 Pingdom 的 YSlow 评分，适合定位请求数、缓存和资源压缩等传统前端优化点；应结合 Lighthouse/WebPageTest 复核 Core Web Vitals。",
            "- 每条 `打开报告` 链接是本次 Pingdom 结果的公开入口，可查看瀑布图、资源类型和响应状态。",
            "",
        ]
    )
    return "\n".join(lines)


def _default_output_path(run_id: str) -> Path:
    return Path(f"artifacts/performance/pingdom-link-performance-{run_id}.md")


def _atomic_write_text(path: Path, content: str) -> None:
    """先写同目录临时文件，再原子替换，避免运行中读取到截断的 checkpoint。"""
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _write_report_files(
    output: Path,
    json_output: Path,
    results: list[PageResult],
    inventory: Path,
    started_at: str,
    snapshot_at: str,
    settings: dict[str, Any],
    skipped_sources: dict[str, int],
    client: PingdomAnonymousClient,
    planned_pages: int,
    run_state: str,
) -> None:
    """保存同一批结果的 Markdown 与 JSON checkpoint。"""
    markdown = build_markdown_report(
        results,
        inventory,
        started_at,
        snapshot_at,
        settings,
        skipped_sources,
        client.rate_limited,
        client.rate_limit_message,
        planned_pages=planned_pages,
        run_state=run_state,
    )
    payload = {
        "started_at": started_at,
        "snapshot_at": snapshot_at,
        "run_state": run_state,
        "inventory": str(inventory),
        "planned_pages": planned_pages,
        "processed_pages": len(results),
        "settings": settings,
        "source_skipped": skipped_sources,
        "rate_limited": client.rate_limited,
        "rate_limit_message": client.rate_limit_message,
        "rate_limit_retries_used": client.rate_limit_retries_used,
        "results": [asdict(item) for item in results],
    }
    _atomic_write_text(output, markdown)
    _atomic_write_text(json_output, json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="低频运行 Pingdom 美国东部站内链接性能测试")
    parser.add_argument("--inventory", type=Path, default=Path("docs/JuJuBit-站内可跳转链接清单.md"))
    parser.add_argument("--output", type=Path, default=None, help="Markdown 报告路径（默认带时间戳）")
    parser.add_argument("--json-output", type=Path, default=None, help="JSON 报告路径（默认与 Markdown 同名）")
    parser.add_argument(
        "--checkpoint-output",
        type=Path,
        default=None,
        help="增量 checkpoint Markdown 路径（默认与最终报告同名并在每页完成后更新）",
    )
    parser.add_argument(
        "--checkpoint-json-output",
        type=Path,
        default=None,
        help="增量 checkpoint JSON 路径（默认与最终 JSON 同名并在每页完成后更新）",
    )
    parser.add_argument("--limit", type=int, default=0, help="仅运行前 N 个页面；0 表示运行归一化后的全部页面")
    parser.add_argument("--region", default=PINGDOM_US_EAST_REGION, help="默认 us-east-1（Washington D.C.）")
    parser.add_argument("--delay", type=float, default=3.0, help="每个 Pingdom API 请求的最小间隔秒数，不能小于 3")
    parser.add_argument("--poll-interval", type=float, default=3.0, help="测试状态轮询间隔秒数")
    parser.add_argument("--poll-timeout", type=float, default=120.0, help="单页面等待 Pingdom metrics 的最大秒数")
    parser.add_argument("--timeout", type=float, default=20.0, help="单个 Pingdom API 请求的网络超时秒数")
    parser.add_argument("--max-rate-limit-retries", type=int, default=3, help="HTTP 429 的最大指数退避重试次数")
    parser.add_argument("--rate-limit-backoff", type=float, default=15.0, help="HTTP 429 的初始退避秒数")
    parser.add_argument("--max-rate-limit-backoff", type=float, default=120.0, help="HTTP 429 的最大退避秒数")
    args = parser.parse_args()

    if args.limit < 0:
        parser.error("--limit 不能为负数")
    if args.region != PINGDOM_US_EAST_REGION:
        parser.error("本脚本固定使用 Pingdom 美国东部节点，请保持 --region us-east-1")
    if args.delay < 3:
        parser.error("--delay 不能小于 3 秒，以避免匿名 Pingdom API 限流")
    if args.poll_interval < 0 or args.poll_timeout <= 0 or args.timeout <= 0:
        parser.error("--poll-interval 不能为负数，--poll-timeout 和 --timeout 必须大于 0")
    if args.max_rate_limit_retries < 0 or args.rate_limit_backoff <= 0 or args.max_rate_limit_backoff <= 0:
        parser.error("429 重试次数不能为负数，退避时间必须大于 0")

    urls, skipped_sources = load_internal_html_urls(args.inventory)
    if args.limit:
        urls = urls[: args.limit]
    started_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    client = PingdomAnonymousClient(
        request_interval=args.delay,
        timeout=args.timeout,
        max_rate_limit_retries=args.max_rate_limit_retries,
        rate_limit_backoff=args.rate_limit_backoff,
        max_rate_limit_backoff=args.max_rate_limit_backoff,
    )
    settings = {
        "region": args.region,
        "request_interval_seconds": args.delay,
        "poll_interval_seconds": args.poll_interval,
        "poll_timeout_seconds": args.poll_timeout,
        "timeout_seconds": args.timeout,
        "max_rate_limit_retries": args.max_rate_limit_retries,
        "rate_limit_backoff_seconds": args.rate_limit_backoff,
        "max_rate_limit_backoff_seconds": args.max_rate_limit_backoff,
        "concurrency": 1,
        "limit": args.limit,
    }
    # 在运行开始即确定输出名，使长任务尚未结束时也能持续查看其 checkpoint。
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    output = args.output or _default_output_path(run_id)
    json_output = args.json_output or output.with_suffix(".json")
    checkpoint_output = args.checkpoint_output or output
    checkpoint_json_output = args.checkpoint_json_output or json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_json_output.parent.mkdir(parents=True, exist_ok=True)

    results: list[PageResult] = []
    for url in urls:
        if client.rate_limited:
            results.append(
                PageResult(
                    url=url,
                    status="跳过（429 保护）",
                    error="前序 Pingdom 请求触发 429 且指数退避已耗尽；为保护匿名额度，本页未提交。",
                )
            )
        else:
            page_result = run_test(client, url, args.region, args.poll_interval, args.poll_timeout)
            results.append(page_result)
        _write_report_files(
            checkpoint_output,
            checkpoint_json_output,
            results,
            args.inventory,
            started_at,
            dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            settings,
            skipped_sources,
            client,
            len(urls),
            "运行中" if len(results) < len(urls) else "已完成",
        )

    finished_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    _write_report_files(
        output,
        json_output,
        results,
        args.inventory,
        started_at,
        finished_at,
        settings,
        skipped_sources,
        client,
        len(urls),
        "已完成",
    )
    print(
        json.dumps(
            {
                "planned": len(urls),
                "completed": sum(item.status.startswith("完成") for item in results),
                "stopped_after_429": client.rate_limited,
                "report": str(output),
                "json": str(json_output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
