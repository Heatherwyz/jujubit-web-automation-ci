"""性能脚本共用的统计与 URL 归一化实现。

抽出这个模块的原因是同一份逻辑此前在多个脚本里各写一遍，并且已经写出了分歧：

- ``_percentile`` 有两种算法。``site_html_link_probe`` 与
  ``generate_website_performance_report`` 用 ``round((n-1)*p)``（最近秩），
  ``pingdom_link_performance`` 用 ``math.ceil(n*p)-1``（上取整秩）。穷举
  n=1..40 与 p=0.5/0.9/0.95 共有 41 组组合选中不同的秩。最实际的后果是
  ``generate_website_performance_report`` 汇总 Pingdom 数据时用了前者，
  而 ``pingdom_link_performance`` 自己用后者，**同一批数据会输出两个 P95**
  （例如 n=115 的递增样本：10900 ms 与 11000 ms）。
- ``normalize_url`` 的静态资源正则曾把 ``jpeg?`` 写成漏掉 ``.jpg`` 的形式。

统一到一处后由 tests/test_metrics.py 覆盖，避免再次漂移。
"""

from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

CANONICAL_HOSTS = frozenset({"jujubit.ai", "www.jujubit.ai"})
CANONICAL_HOST = "jujubit.ai"
# Markdown 行内链接；用于从链接清单里提取待测地址。
LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)]+)\)")
# 静态资源后缀。注意 jpe?g 而不是 jpeg?：后者匹配 .jpe 却匹配不到 .jpg。
ASSET_PATH_RE = re.compile(
    r"\.(?:avif|css|csv|gif|ico|jpe?g|js|json|map|mp[34]|pdf|png|svg|webm|webp|woff2?|zip)$",
    re.IGNORECASE,
)
TRACKING_QUERY_KEYS = frozenset(
    {"_fd", "_sc", "_sid", "_ss", "_y", "pb", "preview_key", "view"}
)
# 会员页的这些参数只决定操作完成后的返回位置，页面本身相同。
MERGED_QUERY_PATHS = frozenset({"/pages/vip-program"})


def percentile(values: Iterable[float], percent: float) -> Optional[float]:
    """离散最近秩分位数；空输入返回 None。

    小样本下不做线性插值：插值会产生实际未观测到的数值，读性能报告时容易被
    误当成真实样本。percent 用 0~1 的小数（0.95 表示 P95）。
    """
    ordered = sorted(values)
    if not ordered:
        return None
    if percent <= 0:
        return ordered[0]
    if percent >= 1:
        return ordered[-1]
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percent))
    return ordered[index]


def canonical_query(query: str) -> str:
    """保留功能参数（variant、page、return_url 等），移除追踪参数。"""
    pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_QUERY_KEYS:
            continue
        # Shopify 有时把同一参数重复拼接；同名同值只保留一次。
        if (key, value) not in pairs:
            pairs.append((key, value))
    return urlencode(sorted(pairs), doseq=True)


def normalize_url(raw_url: str) -> Optional[str]:
    """把清单中的绝对链接归一化为唯一的站内 HTML 页面地址。

    返回 None 表示该链接不是需要测量的站内 HTML 页面（站外、非 HTTP、
    静态资源或 CDN 路径）。
    """
    try:
        parts = urlsplit(raw_url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if host not in CANONICAL_HOSTS or parts.scheme.lower() not in {"http", "https"}:
        return None

    path = parts.path or "/"
    # 集合内的商品链接最终落到同一个商品详情页；统一到 canonical Shopify route。
    match = re.match(r"^/collections/[^/]+/products(/.*)$", path, re.IGNORECASE)
    if match:
        path = "/products" + match.group(1)
    if path != "/":
        path = "/" + path.strip("/")
    if ASSET_PATH_RE.search(path) or path.lower().startswith("/cdn/"):
        return None

    # 锚点不改变服务端返回的 HTML，不能作为独立性能样本。
    query = canonical_query(parts.query)
    if path.lower() in MERGED_QUERY_PATHS:
        query = ""
    return urlunsplit(("https", CANONICAL_HOST, path, query, ""))


def format_bytes(value: object) -> str:
    """把字节数格式化为带单位的字符串；无效值返回 '-'。"""
    try:
        size = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "-"
    if size < 0:
        return "-"
    units = ("B", "KB", "MB", "GB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
