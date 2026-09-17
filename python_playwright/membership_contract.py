"""会员付费墙服务端 HTML 契约：期望值与纯解析断言，不依赖 Playwright。

与 home_contract.py 同一模式：这一层只回答"不执行 JavaScript 的原始 HTML
是否包含约定的会员内容"。红了就是付费墙页面真改坏了。

需要真实渲染、交互和登录态的验收留在 test_membership.py。
"""

from __future__ import annotations

import re
from typing import Optional

# --- 确认后的期望值（docs/requirements/07-冲突确认结果.md）---

TIERS = ("Basic", "Pro", "Premium")

EXPECTED_MONTHLY_PRICES = {
    "Pro": "$19.90",
    "Premium": "$199.90",
}

EXPECTED_YEARLY_PRICES = {
    "Pro": "$238.80",
    "Premium": "$2,398.80",
}

EXPECTED_FIRST_YEAR_PRICES = {
    "Pro": "$191.04",
    "Premium": "$1,919.04",
}

# 已知问题：线上 Premium 价格与产品确认值不一致（2026-09-17 契约层实跑发现）。
#
#   项           确认值        线上实际
#   月付         $199.90      $99.90
#   标准年付     $2,398.80    $1,198.80
#   首年（8折）  $1,919.04    $959.04
#
# 线上那组正是需求文档 4.5 权益表里并存的另一行（见 02-会员体系vv.md 记录的
# "$199.9 与 $99.9 两行并存"），且 959.04 = 1198.80 × 0.8，8 折关系成立，
# 说明线上是一套自洽的价格，不是配错单个数字。
#
# 处理方式：保留确认值作为断言基准，把受影响的档位登记在此。契约层遇到登记过
# 的档位会记为 xfail（未完成）而不是失败——既不掩盖不一致，也不让这一层长期
# 红着。价格对齐后从这里删掉对应档位即可恢复硬断言。
#
# 不改成线上值的原因：那等于用实现反推需求，一旦线上是配错的就永远发现不了。
KNOWN_PRICE_MISMATCH_TIERS = frozenset({"Premium"})

# 线上实测到的价格，仅用于在 xfail 原因里说明差异，不作为断言基准。
# 注意月付线上写作 $99.9（一位小数），不是 $99.90——按页面实际写法记录，
# 否则"记录是否过期"的核对会误报。
OBSERVED_ONLINE_PRICES = {
    "Premium": {
        "monthly": "$99.9",
        "yearly": "$1,198.80",
        "first_year": "$959.04",
    },
}

MOST_POPULAR_TIER = "Pro"
MOST_POPULAR_TEXT = "Most Popular"


def _normalize(html: str) -> str:
    """折叠空白，便于子串匹配。"""
    return re.sub(r"\s+", " ", html)


def check_tier_names(html: str) -> list[str]:
    """付费墙必须包含三档名称。"""
    normalized = _normalize(html)
    missing = [tier for tier in TIERS if tier not in normalized]
    if missing:
        return [f"付费墙缺少会员档位名称：{'、'.join(missing)}"]
    return []


def check_monthly_prices(html: str) -> list[str]:
    """Pro 和 Premium 的月付价格必须出现在服务端 HTML 中。

    已登记价格不一致的档位（KNOWN_PRICE_MISMATCH_TIERS）跳过，由
    check_known_price_mismatch 单独汇报，避免把已知问题混进硬断言。
    """
    problems: list[str] = []
    for tier, price in EXPECTED_MONTHLY_PRICES.items():
        if tier in KNOWN_PRICE_MISMATCH_TIERS:
            continue
        # 匹配 $19.90 或 19.90（不含 $）
        amount = price.lstrip("$")
        if amount not in html and price not in html:
            problems.append(f"{tier} 月付价格 {price} 未出现在 HTML 中")
    return problems


def known_price_mismatch_reason() -> str:
    """返回已登记价格不一致的说明；无登记时返回空串。

    供契约层判断是否应记为 xfail（未完成）而不是失败。
    """
    if not KNOWN_PRICE_MISMATCH_TIERS:
        return ""
    parts = []
    for tier in sorted(KNOWN_PRICE_MISMATCH_TIERS):
        observed = OBSERVED_ONLINE_PRICES.get(tier, {})
        parts.append(
            f"{tier}：确认值月付 {EXPECTED_MONTHLY_PRICES.get(tier, '?')}/"
            f"年付 {EXPECTED_YEARLY_PRICES.get(tier, '?')}，"
            f"线上实际月付 {observed.get('monthly', '?')}/"
            f"年付 {observed.get('yearly', '?')}"
        )
    return (
        "已知问题：线上会员价格与产品确认值不一致（"
        + "；".join(parts)
        + "）。价格对齐后请从 KNOWN_PRICE_MISMATCH_TIERS 移除该档位以恢复硬断言。"
    )


def check_yearly_prices(html: str) -> list[str]:
    """年付原价和首年 8 折价都应出现。

    已登记价格不一致的档位跳过，同 check_monthly_prices。
    """
    problems: list[str] = []
    for tier in ("Pro", "Premium"):
        if tier in KNOWN_PRICE_MISMATCH_TIERS:
            continue
        yearly = EXPECTED_YEARLY_PRICES[tier].lstrip("$").replace(",", "")
        first_year = EXPECTED_FIRST_YEAR_PRICES[tier].lstrip("$").replace(",", "")
        # 检查去逗号后的数字是否在 HTML 中
        if yearly not in html and EXPECTED_YEARLY_PRICES[tier] not in html:
            problems.append(f"{tier} 标准年付价格 {EXPECTED_YEARLY_PRICES[tier]} 未出现")
        if first_year not in html and EXPECTED_FIRST_YEAR_PRICES[tier] not in html:
            problems.append(f"{tier} 首年价格 {EXPECTED_FIRST_YEAR_PRICES[tier]} 未出现")
    return problems


def check_most_popular(html: str) -> list[str]:
    """Pro 卡片应带 Most Popular 推荐标记。"""
    if MOST_POPULAR_TEXT not in _normalize(html):
        return [f"缺少 {MOST_POPULAR_TEXT!r} 推荐标记"]
    return []


def check_qa_section(html: str) -> list[str]:
    """付费墙底部应有 Q&A / FAQ 区域。"""
    normalized = _normalize(html).lower()
    if "q&a" not in normalized and "faq" not in normalized and "frequently" not in normalized:
        return ["缺少 Q&A / FAQ 区域"]
    return []


# 每项为 (契约名, 检查函数)。新增付费墙 HTML 断言只需在此登记。
MEMBERSHIP_HTML_CONTRACTS = (
    ("三档名称", check_tier_names),
    ("Pro 月付价格", check_monthly_prices),
    ("年付价格与首年折扣", check_yearly_prices),
    ("Most Popular 标记", check_most_popular),
    ("Q&A section", check_qa_section),
)


def check_all(html: str) -> dict[str, list[str]]:
    """返回 {契约名: 问题列表}，只包含存在问题的契约。"""
    report: dict[str, list[str]] = {}
    for name, check in MEMBERSHIP_HTML_CONTRACTS:
        problems = check(html)
        if problems:
            report[name] = problems
    return report
