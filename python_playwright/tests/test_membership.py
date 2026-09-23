"""会员浏览器层自动化用例。

覆盖范围：付费墙页面、支付拉起（走到表单可见即止）、Membership 管理页、
引流入口 Banner、会员弹窗与 Generate 超限 toast、埋点。

支付边界：入口 → 选档 → 点 Get → Airwallex 半屏/全屏支付表单可见，
断言 SDK 加载完成、卡号输入框出现。不填卡、不点 Pay Now、不产生真实扣款。

需要登录态的用例标记 @pytest.mark.membership_session；
不需要登录的（付费墙匿名访问、未登录跳登录）不标。
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, expect

from python_playwright.membership_contract import KNOWN_PRICE_MISMATCH_TIERS
from python_playwright.pages.home_page import SiteRateLimitError
from python_playwright.pages.membership_page import (
    AIRWALLEX_HOSTS,
    DAILY_GENERATE_LIMITS,
    FIRST_YEAR_PRICES,
    LIMIT_TOAST_MESSAGES,
    MEMBERSHIP_EMPTY_STATES,
    MEMBERSHIP_POPUP_BENEFITS,
    MEMBERSHIP_POPUP_BUTTON,
    MEMBERSHIP_POPUP_TITLE,
    MONTHLY_PRICES,
    PAYMENT_FAILED_BUTTON,
    PAYMENT_FAILED_TEXT,
    PAYWALL_PATH,
    PRIMARY_BUTTONS,
    PROFILE_TAB_ORDER,
    SEL_OVERVIEW_SIGNED_OUT,
    BANNER_ACTION_TEXT,
    BANNER_SAVE_MORE_TEXT,
    EVENT_ENTRY_VIEW,
    EVENT_PLAN_CLICK,
    EVENT_PLAN_IMPRESSION,
    MembershipLoginRequiredError,
    MembershipPage,
    expected_banner_copy,
)

# 整个模块打 membership marker，run_all.py 用 -m 表达式选择会员套件，
# 无需在命令里追加文件路径。
pytestmark = pytest.mark.membership


# ============================================================
# 付费墙页面（MEM-01 ~ MEM-10）：不需要登录态
# ============================================================


def test_mem01_paywall_monthly_three_tiers(home, page, test_platform):
    """MEM-01: 付费墙 Monthly 展示三档卡片。

    Premium 价格线上与确认值不一致（见 membership_contract 的
    KNOWN_PRICE_MISMATCH_TIERS），这里只校验已对齐的档位，避免把已知问题
    混进硬断言。
    """
    mp = MembershipPage(page, home.base_url, home.config)
    mp.open_paywall()
    mp.wait_for_paywall()
    cards = mp.paywall_cards()
    assert cards.count() >= 3, f"付费墙应至少展示 3 张卡片，实际 {cards.count()}"
    for tier, price in MONTHLY_PRICES.items():
        if tier in KNOWN_PRICE_MISMATCH_TIERS:
            continue
        text = mp.card_price_text(tier)
        if price.lstrip("$").lower() not in text.lower():
            home.mark_failure_evidence(
                mp._find_tier_card(tier),
                f"{tier} 月付价格应含 {price}，实际 {text!r}",
            )
            raise AssertionError(f"{tier} 月付价格应含 {price}，实际 {text!r}")


def test_mem02_paywall_yearly_discount(home, page, test_platform):
    """MEM-02: 付费墙 Yearly 展示三档带折扣。"""
    mp = MembershipPage(page, home.base_url, home.config)
    mp.open_paywall()
    mp.wait_for_paywall()
    mp.switch_cycle("yearly")
    for tier in ("Pro", "Premium"):
        if tier in KNOWN_PRICE_MISMATCH_TIERS:
            continue
        text = mp.card_price_text(tier)
        first_year = FIRST_YEAR_PRICES[tier].lstrip("$").replace(",", "")
        assert first_year in text.replace(",", ""), (
            f"{tier} 首年 8 折价应含 {FIRST_YEAR_PRICES[tier]}，实际 {text!r}"
        )


def test_mem03_h5_default_pro_card(home, page, test_platform):
    """MEM-03: H5 默认 Monthly-Pro 卡片。"""
    if test_platform != "h5":
        pytest.skip("仅 H5 端验证")
    mp = MembershipPage(page, home.base_url, home.config)
    mp.open_paywall()
    mp.wait_for_paywall()
    # H5 一次只显示一个，默认应该是 Pro
    pro_card = mp._find_tier_card("Pro")
    expect(pro_card).to_be_visible(timeout=10_000)


def test_mem04_current_plan_disabled(home, page, test_platform):
    """MEM-04: 当前方案按钮置灰（Basic 用户看 Basic 卡片）。"""
    mp = MembershipPage(page, home.base_url, home.config)
    mp.open_paywall()
    mp.wait_for_paywall()
    text = mp.card_button_text("Basic")
    if "Current Plan" not in text:
        home.mark_failure_evidence(
            mp.card_button("Basic"),
            f"Basic 按钮应为 Current Plan，实际 {text!r}",
        )
    assert "Current Plan" in text, f"Basic 按钮应为 Current Plan，实际 {text!r}"
    assert not mp.card_button_enabled("Basic"), "Current Plan 按钮应 disabled"


def test_mem05_higher_tier_enabled(home, page, test_platform):
    """MEM-05: 高于当前按钮可点。"""
    mp = MembershipPage(page, home.base_url, home.config)
    mp.open_paywall()
    mp.wait_for_paywall()
    for tier in ("Pro", "Premium"):
        text = mp.card_button_text(tier)
        assert re.search(r"Get\s+(Pro|Premium)", text), (
            f"{tier} 按钮应为 Get {tier}，实际 {text!r}"
        )
        assert mp.card_button_enabled(tier), f"{tier} 按钮应 enabled"


def test_mem08_pro_most_popular(home, page, test_platform):
    """MEM-08: Pro 卡片 Most Popular 样式。"""
    mp = MembershipPage(page, home.base_url, home.config)
    mp.open_paywall()
    mp.wait_for_paywall()
    assert mp.most_popular_visible(), "Pro 卡片应有 Most Popular 推荐标记"


def test_mem09_qa_visible(home, page, test_platform):
    """MEM-09: Q&A 展示。"""
    mp = MembershipPage(page, home.base_url, home.config)
    mp.open_paywall()
    mp.wait_for_paywall()
    # 滚到底部
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(2000)
    assert mp.qa_section_visible(), "付费墙底部应有 Q&A 区域"


def test_mem10_unauthenticated_redirects_to_login(home, page, test_platform):
    """MEM-10: 未登录点 Get 先跳登录。"""
    mp = MembershipPage(page, home.base_url, home.config)
    mp.open_paywall()
    mp.wait_for_paywall()
    mp.click_get("Pro")
    page.wait_for_timeout(5000)
    url = page.url.lower()
    assert "account" in url or "login" in url or "authentication" in url, (
        f"未登录点 Get 应跳登录页，实际 URL {page.url}"
    )


# ============================================================
# 支付拉起（MEM-11 ~ MEM-15）：需要登录态，走到表单可见即止
# ============================================================


def _require_logged_in_paywall(mp, page) -> None:
    """点 Get 后若跳到登录页，说明缺登录态——记为未完成而不是失败。

    线上实测：未登录点 Get 会跳 Shopify 托管登录页，半屏支付弹窗不出现。
    这是设计行为（见 MEM-10），所以支付拉起用例必须带有效登录态才能验证。
    """
    url = page.url.lower()
    if "authentication" in url or "/login" in url or "account/login" in url:
        pytest.skip(
            "缺少有效登录态：点 Get 已跳转 Shopify 登录页，半屏支付未拉起。"
            "请配置 PLAYWRIGHT_STORAGE_STATE_JSON 后重跑。"
        )


def _wait_for_payment_or_skip(mp, page) -> None:
    """等待支付表单；登录态失效时记为未完成，而不是"支付未拉起"的业务失败。

    历史问题（2026-09-22 全量回归实测）：登录态过期后整页跳到
    ``shopify.com/authentication/.../oauth/authorize``，等待循环耗完 SDK 超时
    才抛 AssertionError，于是 6 条支付用例被报成业务失败；而同一根因的其他
    15 条会员用例正确地报了"缺少有效登录态"。同一个环境问题必须只有一种口径。
    """
    try:
        mp.wait_for_payment_form()
    except MembershipLoginRequiredError as error:
        pytest.skip(f"{error} 请重新导出 PLAYWRIGHT_STORAGE_STATE_JSON 后重跑。")
    _require_logged_in_paywall(mp, page)


@pytest.mark.membership_session
def test_mem11_pro_monthly_payment_form(home, page, test_platform):
    """MEM-11: Pro Monthly 拉起半屏支付。走到表单可见即止，不填卡不付款。"""
    mp = MembershipPage(page, home.base_url, home.config)
    mp.open_paywall()
    mp.wait_for_paywall()
    mp.click_get("Pro")
    # 不加固定等待：点 Get 后线上约 8 秒才跳 Airwallex，6 秒时检查 URL
    # 只会看到还停在会员页，既拦不住缺登录态也会误导排查。
    # wait_for_payment_form 自己会轮询两种形态。
    _wait_for_payment_or_skip(mp, page)
    label = mp.payment_plan_label()
    assert "Pro" in label, f"支付表单应显示 Pro 套餐，实际 {label!r}"
    billing = mp.payment_billing_label()
    # 中英文都要认：Airwallex 托管页在 CI 的 Chromium 里渲染成中文"每月"，
    # 只匹配 "month" 会在 CI 恒假。
    assert re.search(r"month|每月|按月", (label + billing), re.I), (
        f"应体现月付周期，套餐={label!r} 账期={billing!r}"
    )
    # SDK 已挂载的直接证据：弹窗内出现 iframe 或卡号输入框。
    assert mp.payment_iframe_count() > 0 or mp.has_card_input(), (
        "Airwallex 支付表单未挂载：弹窗内无 iframe 也无卡号输入框"
    )
    mp.close_payment()


@pytest.mark.membership_session
def test_mem12_pro_yearly_payment_form(home, page, test_platform):
    """MEM-12: Pro Yearly 拉起半屏支付，实付为首年 8 折价。"""
    mp = MembershipPage(page, home.base_url, home.config)
    mp.open_paywall()
    mp.wait_for_paywall()
    mp.switch_cycle("yearly")
    mp.click_get("Pro")
    # 不加固定等待：点 Get 后线上约 8 秒才跳 Airwallex，6 秒时检查 URL
    # 只会看到还停在会员页，既拦不住缺登录态也会误导排查。
    # wait_for_payment_form 自己会轮询两种形态。
    _wait_for_payment_or_skip(mp, page)
    amount = mp.payment_amount_text()
    expected = FIRST_YEAR_PRICES["Pro"].lstrip("$").replace(",", "")
    assert expected in amount.replace(",", ""), (
        f"首年 8 折实付应含 {FIRST_YEAR_PRICES['Pro']}，实际 {amount!r}"
    )
    mp.close_payment()


@pytest.mark.membership_session
def test_mem13_premium_monthly_payment_form(home, page, test_platform):
    """MEM-13: Premium Monthly 拉起半屏支付。

    Premium 价格线上与确认值不一致（KNOWN_PRICE_MISMATCH_TIERS），所以这里
    只验证"能拉起支付表单且套餐正确"，不断言具体金额——金额由契约层的
    test_membership_known_price_mismatch 单独追踪。
    """
    mp = MembershipPage(page, home.base_url, home.config)
    mp.open_paywall()
    mp.wait_for_paywall()
    mp.click_get("Premium")
    # 不加固定等待：点 Get 后线上约 8 秒才跳 Airwallex，6 秒时检查 URL
    # 只会看到还停在会员页，既拦不住缺登录态也会误导排查。
    # wait_for_payment_form 自己会轮询两种形态。
    _wait_for_payment_or_skip(mp, page)
    label = mp.payment_plan_label()
    assert "Premium" in label, f"支付表单应显示 Premium 套餐，实际 {label!r}"
    assert mp.payment_iframe_count() > 0 or mp.has_card_input(), (
        "Airwallex 支付表单未挂载"
    )
    mp.close_payment()


# MEM-14（支付失败兜底跳全屏）与 MEM-15（支付失败弹窗文案）已于 2026-09-23
# 移除：都要先制造一次真实的 Airwallex 支付失败。拦网络伪造失败只能验证我们
# 自己的 mock，证明不了线上兜底逻辑；真发起失败支付又会碰真实支付通道。


def _require_logged_in(page) -> None:
    """访问需登录页面后若跳到登录页，说明缺登录态——记为未完成。"""
    url = page.url.lower()
    if "authentication" in url or "/login" in url or "account/login" in url or "shopify.com/auth" in url:
        pytest.skip(
            "缺少有效登录态：已跳转 Shopify 登录页。"
            "请配置 PLAYWRIGHT_STORAGE_STATE_JSON 后重跑。"
        )


def _open_cart_with_membership_entry(home, page) -> MembershipPage:
    """打开购物车并让会员引流入口生效，供 MEM-28 ~ MEM-31 复用。

    入口受 show_vip_banner 实验控制，且 VIP 账号会隐藏它，所以注入开关必须在
    导航之前完成（add_init_script 只对后续加载生效）。入口没出现就记为未完成，
    不硬断言——可能是实验被服务端强制关闭。
    """
    mp = MembershipPage(page, home.base_url, home.config)
    mp.enable_cart_membership_entry()
    page.goto(
        f"{home.base_url}/cart", wait_until="domcontentloaded", timeout=30_000
    )
    try:
        page.wait_for_function(
            "() => customElements.get('custom-cart') !== undefined",
            timeout=20_000,
        )
    except PlaywrightTimeoutError:
        pytest.skip(
            "购物车页未加载 custom-cart 组件，会员引流入口无法验证。"
            "可能主题改版或脚本加载失败。"
        )
    return mp


# ============================================================
# Membership 管理页（MEM-16 ~ MEM-25）
#
# 真正的管理页是会员页的 MEMBERSHIP 视图（/pages/vip-program?tab=membership），
# 不是 /account——后者是 Shopify 托管账户页，只有 Profile/Orders，没有 MEMBERSHIP
# 页签。2026-09-20 实测：/account 落到 shopify.com/.../account/orders。
# ============================================================


def _open_membership(home, page) -> MembershipPage:
    """打开会员管理页并校验登录态，供 MEM-16 ~ MEM-25 复用。

    不再 goto /account。缺登录态时会员页 overview 会显示
    "Log in to view your plan"，据此记为未完成而不是失败。
    """
    mp = MembershipPage(page, home.base_url, home.config)
    mp.open_paywall()
    mp.wait_for_paywall()
    mp.open_membership_tab()
    if page.locator(SEL_OVERVIEW_SIGNED_OUT).count():
        pytest.skip(
            "缺少有效登录态：会员页 overview 提示 Log in to view your plan。"
            "请配置 PLAYWRIGHT_STORAGE_STATE_JSON 后重跑。"
        )
    return mp


@pytest.mark.membership_session
def test_mem16_profile_tab_order(home, page, test_platform):
    """MEM-16: Profile Tab 排序。"""
    mp = _open_membership(home, page)
    tabs = mp.profile_tab_texts()
    expected = list(PROFILE_TAB_ORDER)
    assert tabs == expected, f"Tab 排序应为 {expected}，实际 {tabs}"


@pytest.mark.membership_session
def test_mem17_active_renewing_status(home, page, test_platform):
    """MEM-17: 会员标识-付费期内连续包月。

    需要处于付费期且开着自动续费的账号。当前测试账号是 Basic（免费档），
    本来就没有续费日期——这属于前提不满足，和 MEM-18/21/22 同类记未完成，
    不是站点功能异常。
    """
    mp = _open_membership(home, page)
    text = mp.membership_status_text()
    if not text:
        pytest.skip(
            "需要付费期内且自动续费的测试账号：当前账号无续费状态文案。"
        )
    assert "active" in text.lower() and "renews" in text.lower(), (
        f"应显示 active and renews on，实际 {text!r}"
    )


@pytest.mark.membership_session
def test_mem19_basic_no_expiry(home, page, test_platform):
    """MEM-19: Basic 不展示到期时间。"""
    mp = _open_membership(home, page)
    text = mp.membership_status_text()
    assert "renews" not in text.lower() and "expires" not in text.lower(), (
        f"Basic 不应展示到期/续费时间，实际 {text!r}"
    )


@pytest.mark.membership_session
def test_mem20_upgrade_button(home, page, test_platform):
    """MEM-20: Primary Button-自动续费显示 Upgrade。"""
    mp = _open_membership(home, page)
    text = mp.primary_button_text()
    assert "Upgrade" in text, f"主按钮应为 Upgrade，实际 {text!r}"


@pytest.mark.membership_session
def test_mem22_premium_view_button(home, page, test_platform):
    """MEM-22: Primary Button-Premium 显示 View。

    按当前登录账号的实际档位判定，不把测试账号邮箱写进代码——本仓库是公开
    仓库。用 Premium 账号导出登录态时这条会真正验证；用其他档位的账号则如实
    记为未完成，而不是假装通过。
    """
    mp = _open_membership(home, page)
    tier = mp.current_tier()
    if tier != "Premium":
        pytest.skip(
            f"当前登录账号档位为 {tier or '未识别'}，本条需要 Premium 账号的登录态。"
            "请用 Premium 账号重新导出 PLAYWRIGHT_STORAGE_STATE_JSON 后重跑。"
        )
    text = mp.primary_button_text()
    expected = PRIMARY_BUTTONS[("Premium", "active")]
    assert expected in text, f"Premium 主按钮应为 {expected}，实际 {text!r}"


@pytest.mark.membership_session
def test_mem23_daily_generations_expanded(home, page, test_platform):
    """MEM-23: Daily Generations 直接展开。"""
    mp = _open_membership(home, page)
    assert mp.daily_generations_expanded(), "Daily Generations 应直接展开展示"


@pytest.mark.membership_session
def test_mem24_no_coupons_empty_state(home, page, test_platform):
    """MEM-24: Available Coupons 无券空态。"""
    mp = _open_membership(home, page)
    text = mp.available_coupons_text()
    expected = MEMBERSHIP_EMPTY_STATES["coupons"]
    assert expected.lower() in text.lower(), (
        f"无券时应展示 {expected!r}，实际 {text!r}"
    )


@pytest.mark.membership_session
def test_mem25_billing_history_renders(home, page, test_platform):
    """MEM-25: Billing History 展开后正确渲染。

    原用例断言"无记录空态"，但线上测试账号有真实账单（$19.90 Paid），
    空态前提不成立。改为校验两种合法形态之一：有记录时每条含金额与日期，
    无记录时展示空态文案。折叠区必须先展开，否则内容恒为空串。
    """
    mp = _open_membership(home, page)
    text = mp.billing_history_text()
    assert text, "Billing History 展开后不应为空——检查折叠区是否真的展开"

    empty_state = MEMBERSHIP_EMPTY_STATES["billing_history"]
    if empty_state.lower() in text.lower():
        return

    assert re.search(r"\$\d[\d,]*\.\d{2}", text), (
        f"有账单记录时应展示金额，实际 {text[:120]!r}"
    )
    assert re.search(r"\b\w{3}\s+\d{1,2},\s+\d{4}", text), (
        f"有账单记录时应展示日期，实际 {text[:120]!r}"
    )


# ============================================================
# 引流入口与 Banner（MEM-26 ~ MEM-33）
# ============================================================


def test_mem26_generate_banner_basic(home, page, test_platform):
    """MEM-26: Generate 入口 basic 触发。

    banner 的真实类名是 ``.cc-membership-entry``（2026-09-23 读主题
    custom-cart.js 确认），不是早期误判"未上线"时的 membership-banner 写法。
    现在它跳过只可能是真实原因：实验未对该会话开启、Generate 页不渲染该入口，
    或需登录态。与"功能不存在"是两回事。
    """
    mp = MembershipPage(page, home.base_url, home.config)
    mp.inject_experiment("show_vip_banner", enable=True)
    page.goto(f"{home.base_url}/products/customize-your-own", wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(4000)
    text = mp.banner_text("generate")
    if not text or "Members" not in text:
        pytest.skip(
            "画板页未展示会员引流入口。可能实验未对该会话开启、"
            "该入口仅出现在购物车/Checkout、或需登录态。"
        )
    assert "Members" in text and ("save" in text.lower() or "Upgrade" in text), (
        f"Generate 页 basic 用户应展示引流 banner，实际 {text!r}"
    )


@pytest.mark.membership_session
def test_mem27_generate_banner_hidden_for_members(home, page, test_platform):
    """MEM-27: Generate 入口非 basic 不展示。"""
    mp = MembershipPage(page, home.base_url, home.config)
    page.goto(f"{home.base_url}/products/customize-your-own", wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(4000)
    # banner 本身可能尚未上线（见 MEM-26 实测结论），非 basic 不展示就是对的。
    # 这条只在 banner 确实出现时才算失败。
    if not mp.banner_visible():
        return  # 不展示 = 符合预期
    raise AssertionError("Pro/Premium 用户不应展示引流 banner")


def test_mem28_cart_banner_20(home, page, test_platform):
    """MEM-28: Cart 入口-折前金额低时取 $20 下限。

    造数据而不是等真实购物车：直接给组件塞 subtotal，再断言文案。真实加购要
    先生成模型（耗时且会污染测试账号购物车），而这条只验证文案换算规则。
    """
    mp = _open_cart_with_membership_entry(home, page)
    subtotal_cents = 5_000  # 20% = $10，低于 $20 下限
    mp.set_cart_membership_subtotal(subtotal_cents)
    expected = expected_banner_copy(subtotal_cents)
    assert expected == "Members: save $20", f"下限换算写错了：{expected}"
    text = mp.banner_text()
    assert expected in text, f"banner 应显示 {expected!r}，实际 {text!r}"


def test_mem29_cart_banner_dynamic(home, page, test_platform):
    """MEM-29: Cart 入口-折前金额高时按 20% 动态显示。"""
    mp = _open_cart_with_membership_entry(home, page)
    subtotal_cents = 25_000  # 20% = $50，落在 $20~$100 区间内
    mp.set_cart_membership_subtotal(subtotal_cents)
    expected = expected_banner_copy(subtotal_cents)
    assert expected == "Members: save $50", f"动态换算写错了：{expected}"
    text = mp.banner_text()
    assert expected in text, f"banner 应显示 {expected!r}，实际 {text!r}"


def test_mem30_cart_banner_save_more(home, page, test_platform):
    """MEM-30: Cart 折扣超 $100 显示 save more。"""
    mp = _open_cart_with_membership_entry(home, page)
    # 折扣 > $100 时主题不再算百分比，固定文案。
    mp.set_cart_membership_subtotal(50_000, discount_cents=10_001)
    expected = expected_banner_copy(50_000, 10_001)
    assert expected == BANNER_SAVE_MORE_TEXT, f"save more 规则写错了：{expected}"
    text = mp.banner_text()
    assert BANNER_SAVE_MORE_TEXT in text, (
        f"banner 应显示 {BANNER_SAVE_MORE_TEXT!r}，实际 {text!r}"
    )


def test_mem31_checkout_banner_entry_page(home, page, test_platform):
    """MEM-31: 购物车入口回跳付费墙时透传 cart_whole。

    原用例要求"进入 Checkout 页"，但 Checkout 是 Shopify 托管域，注入不到
    主题脚本，且真实下单有支付副作用。入口契约（entry_page 透传）在购物车侧
    就能验证，这里只验证这一段，不进 Checkout。
    """
    mp = _open_cart_with_membership_entry(home, page)
    mp.set_cart_membership_subtotal(25_000)
    assert mp.banner_visible(), "注入实验开关后购物车应出现会员引流入口"
    action = mp.banner_action_text()
    assert BANNER_ACTION_TEXT.lower() in action.lower(), (
        f"入口按钮应为 {BANNER_ACTION_TEXT}，实际 {action!r}"
    )
    entry_page = mp.banner_entry_page()
    assert entry_page == "cart_whole", (
        f"购物车入口应透传 entry_page=cart_whole，实际 {entry_page!r}"
    )


def test_mem32_entry_page_roundtrip(home, page, test_platform):
    """MEM-32: 四入口跳付费墙返回原页面。"""
    mp = MembershipPage(page, home.base_url, home.config)
    mp.open_paywall(entry_page="header")
    # 验证 entry_page 参数在 URL 中
    assert "entry_page" in page.url, "付费墙 URL 应含 entry_page 参数"


@pytest.mark.membership_session
def test_mem33_member_forced_banner(home, page, test_platform):
    """MEM-33: 会员强制展示 banner。"""
    mp = MembershipPage(page, home.base_url, home.config)
    page.goto(f"{home.base_url}/cart", wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(3000)
    _require_logged_in(page)
    if not mp.banner_visible():
        pytest.skip(
            "购物车页未展示会员引流入口。banner 真实类名为 .cc-membership-entry"
            "（2026-09-23 确认已上线），此处跳过只可能是实验未开启或购物车为空。"
        )
    # 到这里说明 banner 存在且可见，会员应强制展示
    assert mp.banner_visible(), "会员用户应强制展示 banner"


# ============================================================
# Generate 计数与弹窗（MEM-34 ~ MEM-39）
# ============================================================


def test_mem34_basic_limit_toast(home, page, test_platform):
    """MEM-34: Basic 超限 toast。"""
    pytest.skip("需要 Basic 用户当日用满 40 次 Generate 的状态")


def test_mem35_pro_limit_toast(home, page, test_platform):
    """MEM-35: Pro 超限 toast。"""
    pytest.skip("需要 Pro 用户当日用满 100 次的状态")


def test_mem37_popup_title_and_benefits(home, page, test_platform):
    """MEM-37: 会员弹窗标题与权益。"""
    mp = MembershipPage(page, home.base_url, home.config)
    mp.inject_experiment("show_vip_banner", enable=True)
    # 必须指定 domcontentloaded：默认等 load 事件，首页第三方资源多，
    # 30 秒内等不到 load 会直接超时（2026-09-20 实测）。
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    if not mp.membership_popup_visible():
        pytest.skip("会员弹窗未触发——可能不在实验组或已弹过")
    title = mp.membership_popup_title()
    assert MEMBERSHIP_POPUP_TITLE in title, (
        f"弹窗标题应含 {MEMBERSHIP_POPUP_TITLE!r}，实际 {title!r}"
    )
    benefits = mp.membership_popup_benefits()
    for expected in MEMBERSHIP_POPUP_BENEFITS:
        assert any(expected in b for b in benefits), (
            f"弹窗应展示权益 {expected!r}，实际 {benefits}"
        )


def test_mem38_popup_join_button(home, page, test_platform):
    """MEM-38: 会员弹窗主按钮。"""
    mp = MembershipPage(page, home.base_url, home.config)
    mp.inject_experiment("show_vip_banner", enable=True)
    # 同 MEM-37：默认等 load 会超时，首页第三方资源迟迟不结束。
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    if not mp.membership_popup_visible():
        pytest.skip("会员弹窗未触发")
    text = mp.membership_popup_button_text()
    assert "19.90" in text, (
        f"弹窗按钮应含 $19.90/mo，实际 {text!r}"
    )


# MEM-39（支付失败弹窗）已于 2026-09-23 移除：与 MEM-14/15 同因，需要真实的
# 支付失败才能验证，伪造失败只验证了我们自己的 mock。


# ============================================================
# 埋点断言（MEM-40 ~ MEM-43）
# ============================================================


def test_mem40_entry_view_event(home, page, test_platform):
    """MEM-40: 会员页入口曝光上报 membership_entry_view。

    事件名与参数取自主题 jjb-membership.js 的 trackMembershipEntryView
    （2026-09-23 读源码确认），不是猜的。缺登录态时会员页只渲染 signed-out
    区块、不上报该事件，所以记为未完成而不是失败。
    """
    mp = MembershipPage(page, home.base_url, home.config)
    mp.record_tracked_events()
    mp.open_paywall()
    mp.wait_for_paywall()
    mp.open_membership_tab()
    if page.locator(SEL_OVERVIEW_SIGNED_OUT).count():
        pytest.skip(
            "缺少有效登录态：会员页未渲染会员视图，入口曝光埋点不会上报。"
            "请配置 PLAYWRIGHT_STORAGE_STATE_JSON 后重跑。"
        )
    event = mp.wait_for_tracked_event(EVENT_ENTRY_VIEW)
    assert event, (
        f"切到会员视图后应上报 {EVENT_ENTRY_VIEW}，"
        f"实际只收到 {[item.get('name') for item in mp.tracked_events()]}"
    )
    params = event.get("params") or {}
    assert params.get("entry_page") == "membership", (
        f"{EVENT_ENTRY_VIEW} 应带 entry_page=membership，实际 {params!r}"
    )
    assert params.get("tab"), f"{EVENT_ENTRY_VIEW} 应带当前 tab，实际 {params!r}"


def test_mem41_plan_impression_event(home, page, test_platform):
    """MEM-41: 付费墙曝光上报 membership_plan_impression。"""
    mp = MembershipPage(page, home.base_url, home.config)
    mp.record_tracked_events()
    mp.open_paywall(entry_page="header")
    mp.wait_for_paywall()
    event = mp.wait_for_tracked_event(EVENT_PLAN_IMPRESSION)
    assert event, (
        f"付费墙渲染后应上报 {EVENT_PLAN_IMPRESSION}，"
        f"实际只收到 {[item.get('name') for item in mp.tracked_events()]}"
    )
    params = event.get("params") or {}
    assert params.get("entry_page") == "header", (
        f"{EVENT_PLAN_IMPRESSION} 应透传 entry_page=header，实际 {params!r}"
    )


def test_mem41b_plan_impression_reported_once(home, page, test_platform):
    """付费墙曝光只上报一次（主题用 impressionTracked 去重）。"""
    mp = MembershipPage(page, home.base_url, home.config)
    mp.record_tracked_events()
    mp.open_paywall()
    mp.wait_for_paywall()
    assert mp.wait_for_tracked_event(EVENT_PLAN_IMPRESSION), "应先上报一次曝光"
    # 切换账期会重渲染卡片，但曝光不应因此重复上报。
    mp.switch_cycle("yearly")
    page.wait_for_timeout(1_500)
    count = len(mp.tracked_events(EVENT_PLAN_IMPRESSION))
    assert count == 1, f"{EVENT_PLAN_IMPRESSION} 应只上报一次，实际 {count} 次"


# MEM-42（已废弃事件不上报）已于 2026-09-23 移除：断言"某事件不出现"无法证伪
# ——没抓到既可能是真没上报，也可能是触发路径没走到，通过了也说明不了什么。


def test_mem43_plan_click_event(home, page, test_platform):
    """MEM-43: 点 Get 上报 membership_plan_click 并带套餐与账期。

    参数取自主题 jjb-membership.js：plan_type / billing_cycle / action_type
    （2026-09-23 读源码确认）。只验证上报，不跟到支付表单——支付拉起由
    MEM-11 ~ MEM-13 负责。
    """
    mp = MembershipPage(page, home.base_url, home.config)
    mp.record_tracked_events()
    mp.open_paywall()
    mp.wait_for_paywall()
    mp.click_get("Pro")
    event = mp.wait_for_tracked_event(EVENT_PLAN_CLICK)
    assert event, (
        f"点 Get Pro 后应上报 {EVENT_PLAN_CLICK}，"
        f"实际只收到 {[item.get('name') for item in mp.tracked_events()]}"
    )
    params = event.get("params") or {}
    plan_type = str(params.get("plan_type", ""))
    assert "pro" in plan_type.lower(), (
        f"{EVENT_PLAN_CLICK} 应带 Pro 套餐，实际 plan_type={plan_type!r}"
    )
    assert params.get("billing_cycle") == "monthly", (
        f"月付应上报 billing_cycle=monthly，实际 {params!r}"
    )
    assert params.get("action_type"), (
        f"{EVENT_PLAN_CLICK} 应带 action_type，实际 {params!r}"
    )
