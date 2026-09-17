"""会员用例元数据：ID、报告标题、前置条件标签。

与 cart_cases.py 同一模式：conftest 的 CASE_TITLES 从这里导入，
新增用例只改这一处，报告标题自动同步。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class MembershipCase:
    """一条会员用例的元数据。"""

    case_id: str
    report_title: str
    function_name: str


# --- 契约层 ---
_CONTRACT_CASES = [
    ("MEM-C01", "HTML 契约：付费墙包含三档名称", "test_membership_html_contract"),
    ("MEM-C02", "HTML 契约：Pro 月付价格", "test_membership_html_contract"),
    ("MEM-C03", "HTML 契约：Premium 月付价格", "test_membership_html_contract"),
    ("MEM-C04", "HTML 契约：年付价格", "test_membership_html_contract"),
    ("MEM-C05", "HTML 契约：Most Popular 标记", "test_membership_html_contract"),
    ("MEM-C06", "HTML 契约：Q&A section", "test_membership_html_contract"),
]

# --- 浏览器层 ---
MEMBERSHIP_CASES = [
    # 付费墙页面
    MembershipCase("MEM-01", "MEM-01: 付费墙 Monthly 展示三档", "test_mem01_paywall_monthly_three_tiers"),
    MembershipCase("MEM-02", "MEM-02: 付费墙 Yearly 展示三档带折扣", "test_mem02_paywall_yearly_discount"),
    MembershipCase("MEM-03", "MEM-03: H5 默认 Monthly-Pro 卡片", "test_mem03_h5_default_pro_card"),
    MembershipCase("MEM-04", "MEM-04: 当前方案按钮置灰", "test_mem04_current_plan_disabled"),
    MembershipCase("MEM-05", "MEM-05: 高于当前按钮可点", "test_mem05_higher_tier_enabled"),
    MembershipCase("MEM-06", "MEM-06: 低于当前按钮置灰", "test_mem06_lower_tier_disabled"),
    MembershipCase("MEM-07", "MEM-07: 已退订有效期内变 Resume", "test_mem07_cancelled_shows_resume"),
    MembershipCase("MEM-08", "MEM-08: Pro 卡片 Most Popular", "test_mem08_pro_most_popular"),
    MembershipCase("MEM-09", "MEM-09: Q&A 展示", "test_mem09_qa_visible"),
    MembershipCase("MEM-10", "MEM-10: 未登录点 Get 先登录", "test_mem10_unauthenticated_redirects_to_login"),
    # 支付拉起
    MembershipCase("MEM-11", "MEM-11: Pro Monthly 拉起半屏支付", "test_mem11_pro_monthly_payment_form"),
    MembershipCase("MEM-12", "MEM-12: Pro Yearly 拉起半屏支付", "test_mem12_pro_yearly_payment_form"),
    MembershipCase("MEM-13", "MEM-13: Premium Monthly 拉起半屏支付", "test_mem13_premium_monthly_payment_form"),
    MembershipCase("MEM-14", "MEM-14: 支付失败兜底跳全屏", "test_mem14_payment_fallback_fullscreen"),
    MembershipCase("MEM-15", "MEM-15: 支付失败弹窗文案", "test_mem15_payment_failed_dialog"),
    # Membership 管理页
    MembershipCase("MEM-16", "MEM-16: Profile Tab 排序", "test_mem16_profile_tab_order"),
    MembershipCase("MEM-17", "MEM-17: 会员标识-付费期内连续包月", "test_mem17_active_renewing_status"),
    MembershipCase("MEM-18", "MEM-18: 会员标识-付费期内已取消", "test_mem18_active_cancelled_status"),
    MembershipCase("MEM-19", "MEM-19: Basic 不展示到期时间", "test_mem19_basic_no_expiry"),
    MembershipCase("MEM-20", "MEM-20: Primary Button-自动续费显示 Upgrade", "test_mem20_upgrade_button"),
    MembershipCase("MEM-21", "MEM-21: Primary Button-已取消显示 Resume", "test_mem21_resume_button"),
    MembershipCase("MEM-22", "MEM-22: Primary Button-Premium 显示 View", "test_mem22_premium_view_button"),
    MembershipCase("MEM-23", "MEM-23: Daily Generations 直接展开", "test_mem23_daily_generations_expanded"),
    MembershipCase("MEM-24", "MEM-24: Available Coupons 无券空态", "test_mem24_no_coupons_empty_state"),
    MembershipCase("MEM-25", "MEM-25: Billing History 无记录空态", "test_mem25_no_billing_history"),
    # 引流入口
    MembershipCase("MEM-26", "MEM-26: Generate 入口 basic 触发", "test_mem26_generate_banner_basic"),
    MembershipCase("MEM-27", "MEM-27: Generate 入口非 basic 不展示", "test_mem27_generate_banner_hidden_for_members"),
    MembershipCase("MEM-28", "MEM-28: Cart 入口-折扣≤$20", "test_mem28_cart_banner_20"),
    MembershipCase("MEM-29", "MEM-29: Cart 入口-折扣>$20 动态", "test_mem29_cart_banner_dynamic"),
    MembershipCase("MEM-30", "MEM-30: Cart 折扣超 $100 显示 save more", "test_mem30_cart_banner_save_more"),
    MembershipCase("MEM-31", "MEM-31: Checkout 入口固定文案", "test_mem31_checkout_banner_fixed"),
    MembershipCase("MEM-32", "MEM-32: 四入口跳付费墙返回原页面", "test_mem32_entry_page_roundtrip"),
    MembershipCase("MEM-33", "MEM-33: 会员强制展示 banner", "test_mem33_member_forced_banner"),
    # 弹窗与计数
    MembershipCase("MEM-34", "MEM-34: Basic 超限 toast", "test_mem34_basic_limit_toast"),
    MembershipCase("MEM-35", "MEM-35: Pro 超限 toast", "test_mem35_pro_limit_toast"),
    MembershipCase("MEM-36", "MEM-36: Premium 超限 toast", "test_mem36_premium_limit_toast"),
    MembershipCase("MEM-37", "MEM-37: 会员弹窗标题与权益", "test_mem37_popup_title_and_benefits"),
    MembershipCase("MEM-38", "MEM-38: 会员弹窗主按钮", "test_mem38_popup_join_button"),
    MembershipCase("MEM-39", "MEM-39: 支付失败弹窗", "test_mem39_payment_failed_popup"),
    # 埋点
    MembershipCase("MEM-40", "MEM-40: 入口曝光埋点", "test_mem40_entry_view_event"),
    MembershipCase("MEM-41", "MEM-41: 付费墙曝光埋点", "test_mem41_plan_impression_event"),
    MembershipCase("MEM-42", "MEM-42: 已废弃事件不上报", "test_mem42_deprecated_events_absent"),
    MembershipCase("MEM-43", "MEM-43: 套餐点击埋点", "test_mem43_plan_click_event"),
]

MEMBERSHIP_CASES_BY_FUNCTION: Dict[str, MembershipCase] = {
    case.function_name: case for case in MEMBERSHIP_CASES
}

# conftest 的 CASE_TITLES 会用这个 dict
MEMBERSHIP_CASE_TITLES: Dict[str, str] = {
    case.function_name: case.report_title for case in MEMBERSHIP_CASES
}
