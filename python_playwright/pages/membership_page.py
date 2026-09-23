"""会员页面对象：付费墙、Membership 管理页、弹窗、Banner、支付拉起。

设计原则：
- 支付走到拉起即止（Airwallex 半屏/全屏支付表单可见），不填卡不付款。
- 复用 HomePage 的弹窗关闭、限速、登录态检查。
- 实验开关注入从提测单获取的 Statsig 方式。
"""

from __future__ import annotations

import math
import re
import time
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    expect,
)

from python_playwright.pages.home_page import HomePage, SiteRateLimitError


class MembershipLoginRequiredError(RuntimeError):
    """登录态失效导致支付无法拉起，当前用例未完成业务校验。

    与"支付未拉起"必须分开：后者是业务失败，前者只是本轮环境缺登录态。
    """


# --- 确认后的期望值 ---

TIERS = ("Basic", "Pro", "Premium")

MONTHLY_PRICES = {"Basic": "Free", "Pro": "$19.90", "Premium": "$199.90"}
YEARLY_PRICES = {"Pro": "$238.80", "Premium": "$2,398.80"}
FIRST_YEAR_PRICES = {"Pro": "$191.04", "Premium": "$1,919.04"}

DAILY_GENERATE_LIMITS = {"Basic": 40, "Pro": 100, "Premium": 200}

LIMIT_TOAST_MESSAGES = {
    "Basic": (
        "Daily limit reached. Upgrade to Pro for more generations today, "
        "or try again tomorrow."
    ),
    "Pro": (
        "Daily limit reached. Upgrade to Premium for more generations today, "
        "or try again tomorrow."
    ),
    "Premium": "Daily limit reached. Please try again tomorrow.",
}

MOST_POPULAR_TEXT = "Most Popular"

MEMBERSHIP_POPUP_TITLE = "JuJuBit Membership"
MEMBERSHIP_POPUP_SUBTITLE = "Up to $220 in Coupons"
MEMBERSHIP_POPUP_BUTTON = "Join for $19.90/mo"
MEMBERSHIP_POPUP_BENEFITS = (
    "Exclusive savings",
    "More Generations",
    "Faster Generation Speed",
    "Higher Generation Quality",
    "Free Digital crafting",
    "Priority Support",
)

PAYMENT_FAILED_TEXT = "Payment failed. Please try again."
PAYMENT_FAILED_BUTTON = "Retry"

MEMBERSHIP_EMPTY_STATES = {
    "coupons": "No membership coupons available yet.",
    "expired_coupons": "No expired coupons yet.",
    "billing_history": "No billing history yet.",
}

# 会员页顶部的视图切换（2026-09-20 线上实测）。
# 会员页只有这两个 role=tab；Profile / Orders 属于 Shopify 托管账户页
# （shopify.com/<shop_id>/account/...），不在同一个页面上，不能混在一个断言里。
PROFILE_TAB_ORDER = ("MEMBERSHIP", "PLANS")

# 管理页按钮矩阵
PRIMARY_BUTTONS = {
    ("Basic", "active"): "Upgrade",
    ("Pro", "active"): "Upgrade",
    ("Basic", "cancelled"): "Resume",
    ("Pro", "cancelled"): "Resume",
    ("Premium", "active"): "View",
}

# 付费墙按钮状态
PAYWALL_BUTTON_STATES = {
    "current": ("Current Plan", False),
    "higher": (re.compile(r"Get (Pro|Premium)"), True),
    "lower": ("Included", False),
    "resume": ("Resume", True),
}

# 超时分档（复用 cart_page 的模式）
TIMEOUT_BUSINESS = 30_000
TIMEOUT_SDK_LOAD = 45_000
TIMEOUT_UI_RENDER = 10_000
# 会员 offer 弹窗的渲染延迟：2026-09-20 实测 domcontentloaded 后约 9 秒才挂上，
# 留足余量，否则点击前检查不到它，等点 Get 时才出现并拦住事件。
TIMEOUT_OFFER_RENDER = 14_000

PAYWALL_PATH = "/pages/vip-program"
AIRWALLEX_HOSTS = ("checkout.airwallex.com", "checkout-demo.airwallex.com")

# --- 线上实测的选择器（2026-09-17 从 /pages/vip-program 真实 DOM 提取）---
# 不要凭猜写 pricing-card / plan-card 之类：线上主题统一用 jjb-membership-* 前缀。
SEL_PAYWALL = ".jjb-membership-paywall"
SEL_PAYWALL_CARDS = ".jjb-membership-paywall__cards"
SEL_PAYWALL_TOGGLE = ".jjb-membership-paywall__toggle"
SEL_PAYWALL_QA = ".jjb-membership-paywall__qa"
SEL_CARD = ".jjb-membership-card"
SEL_CARD_TITLE = ".jjb-membership-card__title"
SEL_CARD_PRICE = ".jjb-membership-card__price"
SEL_CARD_BUTTON = ".jjb-membership-card__button"
SEL_CARD_BADGE = ".jjb-membership-card__value-badge"
SEL_CARD_FEATURES = ".jjb-membership-card__features"

# 半屏支付弹窗（支付拉起断言的核心）
SEL_CHECKOUT = ".jjb-membership-checkout"
SEL_CHECKOUT_PLAN = ".jjb-membership-checkout__plan"
SEL_CHECKOUT_PRICE = ".jjb-membership-checkout__price"
SEL_CHECKOUT_SUBTOTAL = ".jjb-membership-checkout__subtotal"
SEL_CHECKOUT_BILLING_LABEL = ".jjb-membership-checkout__billing-label"
SEL_CHECKOUT_MOUNT = ".jjb-membership-checkout__mount"
SEL_CHECKOUT_FORM_HOST = ".jjb-membership-checkout__payment-form-host"
SEL_CHECKOUT_LOADING = ".jjb-membership-checkout__loading"
SEL_CHECKOUT_STATUS = ".jjb-membership-checkout__status"
SEL_CHECKOUT_RETRY = ".jjb-membership-checkout__retry"
SEL_CHECKOUT_CLOSE = ".jjb-membership-checkout__close"

# 会员弹窗（开屏 offer）
SEL_OFFER = ".jjb-membership-offer"
SEL_OFFER_BRAND = ".jjb-membership-offer__brand"
SEL_OFFER_SUBTITLE = ".jjb-membership-offer__subtitle"
SEL_OFFER_CTA = ".jjb-membership-offer__cta"
SEL_OFFER_CLOSE = ".jjb-membership-offer__close"
SEL_OFFER_BENEFITS = ".jjb-membership-offer__benefits"
SEL_OFFER_BENEFIT_LABEL = ".jjb-membership-offer__benefit-label"
SEL_OFFER_BENEFIT_VALUE = ".jjb-membership-offer__benefit-value"

# 管理页
SEL_OVERVIEW = ".jjb-membership-overview"
SEL_OVERVIEW_SIGNED_OUT = ".jjb-membership-overview__signed-out"
# Billing History 折叠区：默认收起，展开前 content 恒为空串。
SEL_OVERVIEW_BILLING_CONTENT = ".jjb-membership-overview__billing-content"
SEL_OVERVIEW_BILLING_CARD = ".jjb-membership-overview__billing-card"

# 购物车 / Checkout 的会员引流入口（主题 custom-cart.js 渲染）。
# 历史写法找的是 membership-banner / vip-banner / upgrade-banner，这三个在全站
# 0 命中，于是 MEM-26/33 长期被判成"banner 尚未上线"。2026-09-23 读主题脚本
# 确认真实类名是 cc-membership-entry。
SEL_CART_MEMBERSHIP_ENTRY = ".cc-membership-entry"
SEL_CART_MEMBERSHIP_ENTRY_COPY = ".cc-membership-entry__copy"
SEL_CART_MEMBERSHIP_ENTRY_ACTION = ".cc-membership-entry__action"

# banner 文案规则（同源于 custom-cart.js 的 membershipSavingCopy）：
# - 折扣已超 $100：固定 "Members: save more"
# - 否则按原价 20% 计，下限 $20、上限 $100，渲染成 "Members: save $XX"
# - 读不到金额：回退 "Unlock member-only savings"
BANNER_SAVE_MORE_TEXT = "Members: save more"
BANNER_FALLBACK_TEXT = "Unlock member-only savings"
BANNER_ACTION_TEXT = "Upgrade"
BANNER_SAVING_RATE = 0.2
BANNER_SAVING_MIN_CENTS = 2_000
BANNER_SAVING_MAX_CENTS = 10_000
BANNER_DISCOUNT_SAVE_MORE_CENTS = 10_000


def expected_banner_copy(subtotal_cents: int, discount_cents: int = 0) -> str:
    """按主题规则算出 banner 应显示的文案。

    与 custom-cart.js 的 membershipSavingCopy 同源，写成纯函数是为了能离线
    单测，而不是在用例里重算一遍百分比——那样算错了两边一起错，断言恒真。

    金额格式跟随主题：整元不带小数（$20），非整元保留两位（$20.50）。
    """
    if discount_cents > BANNER_DISCOUNT_SAVE_MORE_CENTS:
        return BANNER_SAVE_MORE_TEXT
    if subtotal_cents <= 0:
        return BANNER_FALLBACK_TEXT
    # JS 的 Math.round 对 .5 向上取整，Python 的 round 是银行家舍入，必须显式处理。
    raw = math.floor(subtotal_cents * BANNER_SAVING_RATE + 0.5)
    saving = min(
        BANNER_SAVING_MAX_CENTS, max(BANNER_SAVING_MIN_CENTS, raw)
    )
    if saving % 100 == 0:
        return f"Members: save ${saving // 100}"
    return f"Members: save ${saving / 100:.2f}"

# 埋点事件名。取自主题 jjb-membership.js 与 custom-cart.js（2026-09-23 读源码
# 确认），不是按文档猜的——早期用例因为拿不到真实事件名而全部无条件跳过。
EVENT_ENTRY_VIEW = "membership_entry_view"
EVENT_PLAN_IMPRESSION = "membership_plan_impression"
EVENT_PLAN_CLICK = "membership_plan_click"
EVENT_CART_ENTRY_CLICK = "membership_entry_click"

# 实验就绪标记：主题注入实验后会加这个 class，可用于等待
SEL_EXPERIMENT_READY = ".jjb-membership-experiment-ready"


class MembershipPage:
    """会员功能的可复用操作集合。"""

    def __init__(self, page: Page, base_url: str, config):
        self.page = page
        self.base_url = base_url.rstrip("/")
        self.config = config
        self.home = HomePage(page, self.base_url, config)

    # ---- 导航 ----

    def open_paywall(self, *, entry_page: str = "header") -> None:
        """打开付费墙页面。

        复用 HomePage.open 的 429 退避与频控熔断，不绕过共享节流器。
        entry_page 的 query 保留在最终 URL 里，入口透传断言依赖它。
        """
        url = f"{self.base_url}{PAYWALL_PATH}"
        if entry_page:
            url += f"?entry_page={entry_page}"
        self.home.open(url)
        self.home.close_welcome_popup()

    def open_membership_tab(self) -> None:
        """切到会员页的 MEMBERSHIP 视图。

        该页签是 role=tab 的按钮，不是 a[href*="membership"]——实测
        a[href*=membership] 在页面上 0 命中，旧选择器会恒假。
        登录态页面的开屏会员 offer（.jjb-membership-offer）会盖住页签，
        必须先关掉，否则点击被拦截（2026-09-20 实测）。
        """
        self.home.close_welcome_popup()
        self.close_membership_popup(observe_timeout=TIMEOUT_OFFER_RENDER)
        tab = self.page.get_by_role("tab", name="Membership").first
        expect(tab).to_be_visible(timeout=TIMEOUT_UI_RENDER)
        tab.click()
        self.page.wait_for_timeout(2000)

    # ---- 实验开关 ----

    def inject_experiment(self, name: str = "show_vip_banner", *, enable: bool = True) -> None:
        """注入 Statsig 实验开关。

        不设 _shop_mode=test：那会让前端走测试环境链路，与线上行为不一致。
        只覆盖 Statsig 实验分组即可。
        """
        value = "true" if enable else "false"
        self.page.evaluate(f"""() => {{
            localStorage.setItem('_statsig_override',
                JSON.stringify({{"{name}": {{"enable": {value}}}}}));
        }}""")

    # ---- 付费墙 ----

    def paywall_cards(self):
        """返回三档卡片的 locator（线上实测 class：jjb-membership-card）。"""
        return self.page.locator(SEL_CARD)

    def wait_for_paywall(self, timeout: int = TIMEOUT_BUSINESS) -> None:
        """等待付费墙卡片区渲染完成。"""
        self.page.wait_for_selector(SEL_CARD, timeout=timeout)
        # 三张卡片都出现后再继续，避免读到渲染中间态。
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            if self.paywall_cards().count() >= 3:
                return
            self.page.wait_for_timeout(300)

    def switch_cycle(self, cycle: str) -> None:
        """切换 Monthly / Yearly。线上是 .jjb-membership-paywall__toggle 内的按钮。

        两种弹窗都要关，它们是不同的遮罩：
        - newsletter 弹窗（.newsletter-popup-v2）：匿名访问时出现，
          MEM-02 曾因此报 __image intercepts pointer events。
        - 会员 offer 弹窗（.jjb-membership-offer）：登录态下约 9 秒后
          渲染成 900px 遮罩，MEM-12 曾卡在这里。
        """
        self.home.close_popup_before_click()
        self.close_membership_popup(observe_timeout=TIMEOUT_OFFER_RENDER)
        label = "Yearly" if cycle.lower() == "yearly" else "Monthly"
        toggle = self.page.locator(SEL_PAYWALL_TOGGLE)
        expect(toggle.first).to_be_visible(timeout=TIMEOUT_UI_RENDER)
        target = toggle.locator(f"button:has-text('{label}'), *:has-text('{label}')").first
        if not target.count():
            target = self.page.locator(f"button:has-text('{label}')").first
        target.click()
        self.page.wait_for_timeout(2000)

    def card_price_text(self, tier: str) -> str:
        """读取指定档位卡片上的价格文案。

        注意用渲染后的 innerText：源码里数字可能被标签分隔（线上 Premium 的
        $99.90 在 HTML 源码里搜不到，渲染后才合并）。
        """
        card = self._find_tier_card(tier)
        if not card.count():
            return ""
        price_el = card.locator(SEL_CARD_PRICE).first
        if price_el.count():
            return re.sub(r"\s+", " ", price_el.inner_text()).strip()
        return re.sub(r"\s+", " ", card.inner_text()).strip()

    def card_button(self, tier: str):
        """返回指定档位卡片上的主按钮。"""
        card = self._find_tier_card(tier)
        return card.locator(SEL_CARD_BUTTON).first

    def card_button_text(self, tier: str) -> str:
        btn = self.card_button(tier)
        return btn.inner_text().strip() if btn.count() else ""

    def card_button_enabled(self, tier: str) -> bool:
        btn = self.card_button(tier)
        if not btn.count():
            return False
        return btn.is_enabled()

    def click_get(self, tier: str) -> None:
        """点击指定档位的 Get/Upgrade 按钮。

        除 newsletter 弹窗外还要关会员 offer 弹窗：登录态下开屏的
        .jjb-membership-offer 会盖住卡片按钮，点击被拦截后只报
        Locator.click timeout，看不出真实原因（2026-09-20 实测）。
        """
        self.home.close_popup_before_click()
        # offer 弹窗在加载后约 9 秒才渲染，必须观察等待而不是立即检查。
        self.close_membership_popup(observe_timeout=TIMEOUT_OFFER_RENDER)
        btn = self.card_button(tier)
        expect(btn).to_be_enabled(timeout=TIMEOUT_UI_RENDER)
        btn.click()

    def most_popular_visible(self) -> bool:
        """Pro 卡片是否带 Most Popular 标记（线上 class：__value-badge）。"""
        card = self._find_tier_card("Pro")
        if not card.count():
            return False
        badge = card.locator(SEL_CARD_BADGE)
        if not badge.count():
            return False
        return MOST_POPULAR_TEXT.lower() in badge.first.inner_text().strip().lower()

    def qa_section_visible(self) -> bool:
        """付费墙底部 Q&A 是否存在（线上 class：__qa）。"""
        return bool(self.page.locator(SEL_PAYWALL_QA).count())

    def _find_tier_card(self, tier: str):
        """按标题精确定位档位卡片。"""
        return self.page.locator(SEL_CARD).filter(
            has=self.page.locator(SEL_CARD_TITLE, has_text=re.compile(rf"^\s*{tier}\s*$"))
        ).first

    # ---- 支付拉起 ----

    def payment_layer_visible(self) -> bool:
        """半屏支付弹窗容器是否出现。"""
        layer = self.page.locator(SEL_CHECKOUT)
        return bool(layer.count()) and layer.first.is_visible()

    def on_customer_login_page(self) -> bool:
        """当前是否已跳到 Shopify 托管的登录/授权页。

        登录态失效时点 Get 会整页跳到
        ``shopify.com/authentication/<id>/oauth/authorize``，半屏支付永不出现。
        这属于"本轮未完成"，不是支付功能坏了，所以要和支付未拉起区分开。
        """
        url = (self.page.url or "").lower()
        return any(
            marker in url
            for marker in ("/authentication/", "/account/login", "/login")
        )

    def storefront_signed_out(self) -> bool:
        """会员页 overview 是否处于未登录态。

        登录态失效有两种形态，只认跳登录页会漏判一半：
        1. 整页跳 shopify.com/authentication/...（on_customer_login_page）
        2. 点 Get 后跳 ?plan=PRO&billingCycle=... 再**跳回会员页**，
           压根不去登录页，支付弹窗永不出现（2026-09-23 实测 MEM-11/12/13
           三条全被误报成"支付未拉起"的业务失败）。

        第 2 种只能靠 overview 判定：未登录时它显示 "Log in to view your
        plan"，登录后显示账号邮箱。
        """
        try:
            return bool(
                self.page.evaluate(
                    """(selSignedOut) => {
                        const explicit = document.querySelector(selSignedOut);
                        if (explicit && explicit.offsetParent) return true;
                        const ov = document.querySelector('.jjb-membership-overview');
                        if (!ov) return false;
                        const text = ov.innerText || '';
                        if (/log in to view your plan/i.test(text)) return true;
                        // 有 overview 但读不到邮箱，同样按未登录处理。
                        return !/[\\w.+-]+@[\\w.-]+\\.\\w+/.test(text);
                    }""",
                    SEL_OVERVIEW_SIGNED_OUT,
                )
            )
        except PlaywrightError:
            # 正在跳转时读不到 DOM，交给下一轮判断。
            return False

    def on_airwallex_hosted_page(self) -> bool:
        """当前是否已跳到 Airwallex 全屏托管支付页。

        2026-09-20 线上实测：登录态下点 Get Pro 会直接跳
        checkout.airwallex.com/pay，站内半屏容器不出现。两种形态都算
        "支付已拉起"，断言不能只认半屏。
        """
        url = (self.page.url or "").lower()
        return any(host in url for host in AIRWALLEX_HOSTS)

    def wait_for_payment_form(self, timeout: int = TIMEOUT_SDK_LOAD) -> None:
        """等待支付表单（Airwallex SDK）加载完成。

        线上有两种形态，都停在"表单可见"即止，不填卡不点 Pay Now：
        - 站内半屏弹窗 .jjb-membership-checkout
        - 跳转 Airwallex 全屏托管页 checkout.airwallex.com/pay
        """
        # 判定用可见性而不是 count()：.jjb-membership-checkout 始终存在于 DOM
        # （隐藏态 count() 恒为 1，且预置了 'Pro Membership'、'$19.90' 模板
        # 文案），用 count() 会立刻误判成"半屏已出现"并读到假数据。
        #
        # 跳转检测必须贯穿整个等待过程，不能只在开头查一次：线上点 Get 后是
        # 整页跳转到 Airwallex，跳转途中对旧 DOM 求值会直接抛
        # "Execution context was destroyed"（2026-09-20 实测）。
        deadline = time.monotonic() + timeout / 1000
        last_state = "未知"
        while time.monotonic() < deadline:
            if self.on_airwallex_hosted_page():
                self._wait_for_hosted_payment_ready(timeout)
                return
            # 跳到 Shopify 登录页说明登录态失效，半屏支付不可能再出现。
            # 必须在这里立刻中止：否则会耗完 SDK 超时，再把"未完成"误报成
            # "支付未拉起"的业务失败（2026-09-22 全量回归实测 6 条）。
            if self.on_customer_login_page():
                raise MembershipLoginRequiredError(
                    "缺少有效登录态：点 Get 已跳转 Shopify 登录页，半屏支付未拉起。"
                    f"当前地址 {self.page.url[:120]}"
                )
            try:
                state = self.page.evaluate(
                    """([selRoot, selMount, selHost, selLoading]) => {
                        const visible = (el) => Boolean(
                            el
                            && el.offsetParent
                            && el.getBoundingClientRect().height > 0
                        );
                        const root = document.querySelector(selRoot);
                        const mount = document.querySelector(selMount);
                        const loading = document.querySelector(selLoading);
                        return {
                            rootVisible: visible(root),
                            mountChildren: mount ? mount.children.length : -1,
                            hasHost: Boolean(document.querySelector(selHost)),
                            loadingVisible: visible(loading),
                            frames: document.querySelectorAll(
                                '.jjb-membership-checkout iframe'
                            ).length,
                        };
                    }""",
                    [
                        SEL_CHECKOUT,
                        SEL_CHECKOUT_MOUNT,
                        SEL_CHECKOUT_FORM_HOST,
                        SEL_CHECKOUT_LOADING,
                    ],
                )
            except PlaywrightError:
                # 正在跳转，下一轮由 on_airwallex_hosted_page 接管。
                self.page.wait_for_timeout(500)
                continue
            last_state = str(state)
            # 半屏就绪：容器可见，且出现 iframe 或挂载点有内容且 loading 已消失。
            if state.get("rootVisible"):
                if state.get("frames", 0) > 0:
                    return
                if state.get("mountChildren", 0) > 0 and not state.get(
                    "loadingVisible"
                ):
                    return
            # 回到会员页且 overview 是未登录态：站点把支付流程退回了。
            # 这是登录态失效的第二种形态（不跳登录页，跳 ?plan=... 再跳回），
            # 必须报未完成而不是耗完超时再误判成"支付未拉起"。
            if self.storefront_signed_out():
                raise MembershipLoginRequiredError(
                    "缺少有效登录态：点 Get 后被退回会员页，overview 仍要求登录，"
                    f"半屏支付未拉起。当前地址 {self.page.url[:120]}"
                )
            self.page.wait_for_timeout(500)

        raise AssertionError(
            f"支付未拉起：半屏弹窗（{SEL_CHECKOUT}）未就绪，也没跳到 Airwallex "
            f"托管页。当前地址 {self.page.url[:100]}，最后状态：{last_state}"
        )

    def _wait_for_hosted_payment_ready(self, timeout: int) -> None:
        """等 Airwallex 全屏托管页的 dropin 表单挂载完成。

        托管页没有站内那套 class，判定依据是 dropin iframe 已加载，
        并且页面展示了套餐与金额。同样停在表单可见，不填卡不提交。
        """
        deadline = time.monotonic() + timeout / 1000
        last_state = "未知"
        while time.monotonic() < deadline:
            state = self.page.evaluate(
                """() => {
                    const frames = Array.from(document.querySelectorAll('iframe'))
                        .map((f) => f.src || '');
                    const text = (document.body && document.body.innerText) || '';
                    return {
                        dropin: frames.some((src) => /elements\\/dropin/i.test(src)),
                        frames: frames.length,
                        hasAmount: /\\$\\d[\\d,]*\\.\\d{2}/.test(text),
                        hasPlan: /membership/i.test(text),
                    };
                }"""
            )
            last_state = str(state)
            if state.get("dropin") and state.get("hasAmount"):
                return
            self.page.wait_for_timeout(500)

        raise AssertionError(
            f"Airwallex 托管支付页未在 {timeout}ms 内就绪，最后状态：{last_state}"
        )

    def _hosted_summary_text(self) -> str:
        """Airwallex 托管页左侧订单摘要的整段文案。

        托管页没有站内那套 jjb-* class，只能读可见文本。摘要里含套餐名、
        账期与金额，足够支撑"拉起了哪一档、金额对不对"的断言。
        """
        try:
            body = self.page.locator("body").first.inner_text()
        except PlaywrightError:
            return ""
        return re.sub(r"\s+", " ", body).strip()

    def _visible_text(self, selector: str) -> str:
        """只在节点真正可见时返回文案，否则空串。

        站内半屏的 __plan / __price / __billing-label 在未拉起支付时就已经
        存在于 DOM，且预置了 'Pro Membership'、'$19.90' 这类模板文案
        （2026-09-20 实测）。用 count() 读会拿到与当前档位无关的假数据——
        Premium 用例也会读到 Pro 的文案，断言假过或假失败。
        """
        node = self.page.locator(selector)
        if not node.count():
            return ""
        try:
            if not node.first.is_visible():
                return ""
            return re.sub(r"\s+", " ", node.first.inner_text()).strip()
        except PlaywrightError:
            return ""

    def payment_plan_label(self) -> str:
        """支付表单里的套餐标签，如 'Pro Membership · Monthly'。

        托管页的判定必须与语言无关：同一页面在 pytest 的 Chromium 里渲染成
        中文（"订阅 JuJuBit Pro Membership"），手工打开时是英文
        （"Subscribe to ..."）。按英文文案匹配会在 CI 里恒空，导致
        "手工能过、用例必败"（2026-09-20 实测踩到）。
        所以锚点取语言无关的套餐名本身：<Brand> <Tier> Membership。
        """
        inline = self._visible_text(SEL_CHECKOUT_PLAN)
        if inline:
            return inline
        if self.on_airwallex_hosted_page():
            match = re.search(
                r"([\w][\w\s]*?(?:Basic|Pro|Premium)\s+Membership)",
                self._hosted_summary_text(),
                re.I,
            )
            if match:
                return match.group(1).strip()
        return ""

    def payment_billing_label(self) -> str:
        """支付表单里的账期说明，如 'Billed monthly, in advance'。"""
        inline = self._visible_text(SEL_CHECKOUT_BILLING_LABEL)
        if inline:
            return inline
        if self.on_airwallex_hosted_page():
            summary = self._hosted_summary_text()
            # 中英文都要认：英文 "Billed monthly"，中文 "每月 预付结算"。
            for pattern in (
                r"Billed\s+(?:monthly|yearly|annually)[^.]*",
                r"每(?:月|年)[^。\s]*(?:\s*预付结算)?",
                r"按(?:月|年)[^。\s]*",
            ):
                match = re.search(pattern, summary, re.I)
                if match:
                    return match.group(0).strip()
        return ""

    def payment_amount_text(self) -> str:
        """支付表单里的实付金额文案。"""
        for sel in (SEL_CHECKOUT_PRICE, SEL_CHECKOUT_SUBTOTAL):
            text = self._visible_text(sel)
            if text and re.search(r"[\d.]+", text):
                return text
        if self.on_airwallex_hosted_page():
            summary = self._hosted_summary_text()
            # 取"今日应付"金额：它是摘要里第一个紧跟 USD 的金额。
            #
            # 不能按标签往后捕获：中文版把标签放在金额后面
            # （"$191.04 USD 今日应付金额"），往后捕获会抓到下一行的小计
            # 原价 $238.80，把已生效的首年折扣误判成没打折（2026-09-20 实测）。
            # 英文同构（"$191.04 USD Due today"），所以锚 USD 与语言无关。
            match = re.search(r"(\$[\d,]+\.\d{2})\s*USD", summary, re.I)
            if match:
                return match.group(1)
            amounts = re.findall(r"\$[\d,]+\.\d{2}", summary)
            if amounts:
                return " ".join(amounts)
        return ""

    def has_card_input(self) -> bool:
        """卡号输入框是否出现（Airwallex SDK 通常渲染在 iframe 内）。"""
        selector = (
            "input[name*='card' i], input[placeholder*='card' i], "
            "input[autocomplete='cc-number'], input[name*='number' i]"
        )
        if self.page.locator(selector).count():
            return True
        for frame in self.page.frames:
            try:
                if frame.locator(selector).count():
                    return True
            except PlaywrightError:
                continue
        return False

    def payment_iframe_count(self) -> int:
        """支付表单内的 iframe 数量——SDK 已挂载的直接证据。

        托管页的 dropin 是顶层 iframe，不在 jjb-* 容器内，所以两种形态
        分别统计。
        """
        inline = self.page.locator(f"{SEL_CHECKOUT} iframe").count()
        if inline:
            return inline
        if self.on_airwallex_hosted_page():
            return self.page.locator("iframe[src*='elements/dropin']").count()
        return 0

    def payment_status_text(self) -> str:
        """支付弹窗里的状态/错误文案。"""
        status = self.page.locator(SEL_CHECKOUT_STATUS)
        if status.count():
            return re.sub(r"\s+", " ", status.first.inner_text()).strip()
        return ""

    def payment_retry_button(self):
        """支付失败后的 Retry 按钮。"""
        return self.page.locator(SEL_CHECKOUT_RETRY).first

    def is_fullscreen_checkout(self) -> bool:
        """当前是否已跳到 Airwallex 全屏 Hosted Checkout 页面。"""
        host = urlparse(self.page.url).hostname or ""
        return any(h in host for h in AIRWALLEX_HOSTS)

    def close_payment(self) -> None:
        """离开支付表单。不填卡、不提交任何支付信息。

        站内半屏点关闭按钮；已跳到 Airwallex 托管页时没有关闭按钮，
        退回会员页即可——不会产生任何扣款。
        """
        close = self.page.locator(SEL_CHECKOUT_CLOSE).first
        if close.count() and close.is_visible():
            close.click()
            self.page.wait_for_timeout(1000)
            return
        if self.on_airwallex_hosted_page():
            try:
                self.page.go_back(wait_until="domcontentloaded", timeout=30_000)
                self.page.wait_for_timeout(1000)
            except PlaywrightError:
                # 托管页偶发不支持回退，留在原页即可，不影响后续 case
                # （每条 case 用独立 Page）。
                pass

    # ---- 支付失败 ----

    def payment_failed_dialog_text(self) -> str:
        """支付失败弹窗的文案。"""
        dialog = self.page.locator(
            "[class*='error'], [class*='failed'], [class*='dialog']"
        ).filter(has_text=re.compile(r"Payment failed|payment failed", re.I))
        if dialog.count():
            return dialog.first.inner_text().strip()
        return ""

    def payment_failed_retry_button(self):
        """支付失败弹窗的 Retry 按钮。"""
        return self.page.get_by_role("button", name="Retry").or_(
            self.page.locator("button:has-text('Retry'), button:has-text('Try Again')")
        ).first

    # ---- Membership 管理页 ----

    def profile_tab_texts(self) -> list[str]:
        """会员页顶部视图切换的 Tab 文案列表。

        只读 [role=tab]，不用 [class*='tab'] 这类宽选择器：后者会同时命中
        父容器和子按钮，拿到 ['MEMBERSHIP\\nPLANS', 'MEMBERSHIP'] 这种
        父子混杂的结果（2026-09-20 实测）。
        只取视图切换的那一组，排除档位周期切换（Monthly / Yearly）。
        """
        tabs = self.page.get_by_role("tab")
        texts = []
        for index in range(tabs.count()):
            raw = tabs.nth(index).inner_text().strip().upper()
            # Yearly 页签带折扣副标题，按首行判断即可。
            first_line = raw.splitlines()[0].strip() if raw else ""
            if first_line in {"MONTHLY", "YEARLY"} or first_line.startswith("YEARLY"):
                continue
            if first_line:
                texts.append(first_line)
        return texts

    def membership_status_text(self) -> str:
        """管理页顶部的会员状态文案。"""
        status = self.page.locator(
            "[class*='status'], [class*='plan-info'], [class*='membership-header']"
        ).filter(has_text=re.compile(r"(active|expires|renews)", re.I))
        if status.count():
            return status.first.inner_text().strip()
        return ""

    def primary_button_text(self) -> str:
        """管理页主按钮文案（Upgrade / Resume / View）。"""
        btn = self.page.locator(
            "[class*='primary'] button, [class*='membership'] button"
        ).filter(has_text=re.compile(r"Upgrade|Resume|View", re.I))
        if btn.count():
            return btn.first.inner_text().strip()
        return ""

    def current_tier(self) -> str:
        """当前登录账号的会员档位，读不到则返回空串。

        取付费墙容器的 ``data-membership-plan``，不要扫 overview 的可见文本：
        权益区里本身就有 "Upgrade to Premium for more generations" 这类文案，
        按文本匹配会把 Basic 账号误判成 Premium，断言随之假过。

        线上该属性的取值是大写的 BASIC / PRO / PREMIUM，另有 PRIME 作为
        PREMIUM 的历史别名（2026-09-23 实测 CSS 里两者同时被样式命中）。
        用于按账号实际档位决定断言，而不是把测试账号邮箱写进代码——本仓库
        是公开仓库，不放任何账号标识。
        """
        paywall = self.page.locator(SEL_PAYWALL)
        if not paywall.count():
            return ""
        raw = (paywall.first.get_attribute("data-membership-plan") or "").strip()
        if not raw:
            return ""
        normalized = raw.upper()
        if normalized == "PRIME":
            return "Premium"
        return {"BASIC": "Basic", "PRO": "Pro", "PREMIUM": "Premium"}.get(
            normalized, ""
        )

    def daily_generations_expanded(self) -> bool:
        """Daily Generations 区域是否直接展开。"""
        section = self.page.locator(
            "[class*='generation'], [class*='daily']"
        ).filter(has_text=re.compile(r"Daily|Generation", re.I))
        if not section.count():
            return False
        # 检查是否有额度数字可见（展开态才有）
        return bool(re.search(r"\d+\s*/\s*\d+", section.first.inner_text()))

    def daily_generations_display(self) -> dict[str, str]:
        """Daily Generations 展开后的数据。"""
        section = self.page.locator(
            "[class*='generation'], [class*='daily']"
        ).filter(has_text=re.compile(r"Daily|Generation", re.I))
        if not section.count():
            return {}
        text = section.first.inner_text()
        return {"raw": text}

    def available_coupons_text(self) -> str:
        """Available Coupons 区域的文案（含空态）。"""
        section = self.page.locator(
            "[class*='coupon'], [class*='available']"
        ).filter(has_text=re.compile(r"coupon|available", re.I))
        if section.count():
            return section.first.inner_text().strip()
        return ""

    def expand_billing_history(self) -> bool:
        """展开 Billing History 折叠区，返回是否点到了标题。

        该区默认收起，不点开时 __billing-content 恒为空串——旧断言据此
        比对文案会永远拿到 ''（2026-09-20 实测）。
        """
        title = self.page.get_by_text("Billing History", exact=True).first
        if not title.count():
            return False
        title.click()
        # 展开后前端异步拉取，__billing-status 会短暂显示 Loading。
        self.page.wait_for_timeout(2_500)
        return True

    def billing_history_text(self) -> str:
        """Billing History 展开后的文案（含空态）。"""
        self.expand_billing_history()
        content = self.page.locator(SEL_OVERVIEW_BILLING_CONTENT).first
        if content.count():
            return content.inner_text().strip()
        return ""

    # ---- 引流 Banner ----

    def banner_text(self, page_name: str = "") -> str:
        """当前页面的会员引流 banner 文案。

        线上真实类名是 ``.cc-membership-entry``（由主题 custom-cart.js 渲染），
        不是历史写法里的 ``membership-banner`` / ``vip-banner``——那两个在全站
        0 命中，导致 MEM-26/33 长期被判成"banner 未上线"（2026-09-23 核实）。
        """
        banner = self.page.locator(SEL_CART_MEMBERSHIP_ENTRY)
        if banner.count():
            return banner.first.inner_text().strip()
        copy = self.page.locator(SEL_CART_MEMBERSHIP_ENTRY_COPY)
        if copy.count():
            return copy.first.inner_text().strip()
        return ""

    def banner_visible(self) -> bool:
        """会员引流 banner 是否可见。"""
        return bool(self.banner_text())

    def banner_action_text(self) -> str:
        """banner 上的行动按钮文案（线上为 Upgrade）。"""
        action = self.page.locator(SEL_CART_MEMBERSHIP_ENTRY_ACTION)
        if action.count():
            return action.first.inner_text().strip()
        return ""

    def banner_entry_page(self) -> str:
        """banner 按钮回跳付费墙时透传的 entry_page。"""
        action = self.page.locator(SEL_CART_MEMBERSHIP_ENTRY_ACTION)
        if not action.count():
            return ""
        fallback = action.first.get_attribute("data-fallback-url") or ""
        match = re.search(r"entry_page=([^&]+)", fallback)
        return match.group(1) if match else ""

    def set_cart_membership_subtotal(
        self, subtotal_cents: int, *, discount_cents: int = 0
    ) -> None:
        """构造购物车金额并重渲染会员入口，避免真实加购的副作用。

        沿用 cart_page.set_shipping_boundary_total 的既有做法：只改前端组件的
        金额字段。真实造 $250 购物车要先生成模型再加购，既慢又会污染测试账号，
        而这几条只验证文案换算规则，不验证结算金额。

        主题的 membershipSavingCopy 读 getOriginalSubtotalCents()（original_total
        优先，回退 items_subtotal_price）与 cart.total_discount，所以三个字段都要设。
        """
        assert subtotal_cents >= 0 and discount_cents >= 0
        self.page.wait_for_function(
            "() => customElements.get('custom-cart') !== undefined",
            timeout=TIMEOUT_BUSINESS,
        )
        result = self.page.evaluate(
            """([subtotal, discount]) => {
                const host = document.querySelector('custom-cart');
                if (!host) {
                    return {ok: false, reason: '页面没有 custom-cart 组件'};
                }
                if (typeof host.membershipEntryHtml !== 'function') {
                    return {ok: false, reason: '组件缺少 membershipEntryHtml()'};
                }
                // membershipEntryHtml() 开头就检查这个标志，为假直接返回空串。
                // 它由主题的 getMembershipCartEntryEnabled() 决定，而该函数受
                // 服务端实验分配控制、返回 false（2026-09-23 实测），测试侧无法
                // 影响。这里直接置真：本组用例验证的是"入口开启后的文案换算"，
                // 实验分配本身由 MEM-27 覆盖。
                host._membershipCartEntryEnabled = true;
                host.cart = {
                    ...(host.cart || {}),
                    item_count: Math.max(1, (host.cart && host.cart.item_count) || 1),
                    original_total_price: subtotal,
                    items_subtotal_price: subtotal,
                    total_price: subtotal,
                    total_discount: discount,
                };
                const slot = host.querySelector('.cc-membership-slot');
                if (!slot) {
                    return {ok: false, reason: '未找到 .cc-membership-slot 挂载点'};
                }
                slot.innerHTML = host.membershipEntryHtml('cart_whole');
                return {ok: true, html: slot.innerHTML.slice(0, 200)};
            }""",
            [subtotal_cents, discount_cents],
        )
        assert result and result.get("ok"), (
            "构造购物车会员入口失败："
            f"{(result or {}).get('reason', '页面未返回状态')}"
        )

    def record_tracked_events(self) -> None:
        """开始记录主题上报的埋点事件。必须在导航之前调用。

        拦 ``window.zlog.track`` 而不是抓网络：zlog 会异步转发到 GA / monorail，
        可能批量合并、被广告拦截器掐断，或因 ``awaitGa4`` 延迟到断言之后——那样
        断言的是投递渠道，不是主题有没有按约定上报。这里断言的是契约本身：
        主题用什么事件名、带什么参数调用了 track。

        zlog 由另一个脚本后置注入，直接赋值会被覆盖，所以用属性 setter 包住：
        无论 zlog 何时被赋值，track 都会先记录再转发给真实实现。
        """
        self.page.add_init_script(
            """
            (() => {
                window.__jjbTrackedEvents = [];
                const record = (name, params) => {
                    try {
                        window.__jjbTrackedEvents.push({
                            name: String(name),
                            params: params || {},
                        });
                    } catch (e) {}
                };
                // 只包一次 track 不够：zlog 脚本会在自己初始化完成后，往同一个
                // 对象上重新赋值 track，把包装覆盖掉——实测表现是 __jjbWrapped
                // 为 true 但一条事件都收不到。所以改成守住 track 这个属性本身：
                // 谁再赋值，都会被重新包一层。
                const wrap = (target) => {
                    if (!target || target.__jjbWrapped) return target;
                    let inner = target.track;
                    const proxy = function (name, params, options) {
                        record(name, params);
                        if (typeof inner === 'function') {
                            return inner.apply(this, arguments);
                        }
                        return undefined;
                    };
                    try {
                        Object.defineProperty(target, 'track', {
                            configurable: true,
                            get: () => proxy,
                            set: (value) => {
                                inner = value;
                            },
                        });
                        target.__jjbWrapped = true;
                    } catch (e) {
                        target.track = proxy;
                    }
                    return target;
                };
                let current = wrap(window.zlog) || undefined;
                Object.defineProperty(window, 'zlog', {
                    configurable: true,
                    get: () => current,
                    set: (value) => {
                        current = wrap(value);
                    },
                });
                // zlog 尚未注入时也要能记录，否则早于脚本的上报会丢。
                if (!current) {
                    current = wrap({});
                }
            })();
            """
        )

    def tracked_events(self, name: str = "") -> list[dict]:
        """取已记录的埋点事件，可按事件名过滤。"""
        events = self.page.evaluate("() => window.__jjbTrackedEvents || []")
        if not isinstance(events, list):
            return []
        if not name:
            return events
        return [item for item in events if item.get("name") == name]

    def wait_for_tracked_event(
        self, name: str, timeout: int = TIMEOUT_BUSINESS
    ) -> dict:
        """等某个埋点事件出现并返回它；超时返回空字典。"""
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            matched = self.tracked_events(name)
            if matched:
                return matched[0]
            self.page.wait_for_timeout(300)
        return {}

    def enable_cart_membership_entry(self) -> None:
        """让购物车的会员引流入口对当前会话生效。

        主题的判定链（custom-cart.js / cart 模板，2026-09-23 读源码确认）：
        ``isTest()`` 认 ``localStorage._shop_mode === 'test'``，此时实验开关
        走 ``window.jjbUtils.overrideExperiment``；入口还要求
        ``getMembershipCartEntryEnabled()`` 为真。VIP 账号会**隐藏**入口
        （``isVipCustomer()`` 直接返回空串），所以这条链路只对非会员有效。
        """
        self.page.add_init_script(
            """
            try { localStorage.setItem('_shop_mode', 'test'); } catch (e) {}
            window.jjbUtils = window.jjbUtils || {};
            window.jjbUtils.overrideExperiment = function () {
                return { get: function (key, fallback) {
                    return key === 'enable' ? true : fallback;
                } };
            };
            window.jjbUtils.getMembershipCartEntryEnabled = function () {
                return Promise.resolve(true);
            };
            """
        )

    # ---- 弹窗 ----

    def membership_popup_visible(self) -> bool:
        """会员开屏弹窗是否可见（线上 class：jjb-membership-offer）。"""
        popup = self.page.locator(SEL_OFFER)
        return bool(popup.count()) and popup.first.is_visible()

    def membership_popup_title(self) -> str:
        """弹窗品牌标题（线上 class：__brand）。"""
        brand = self.page.locator(SEL_OFFER_BRAND)
        if brand.count():
            return re.sub(r"\s+", " ", brand.first.inner_text()).strip()
        return ""

    def membership_popup_subtitle(self) -> str:
        """弹窗副标题，如 'Up to $220 in Coupons'。"""
        sub = self.page.locator(SEL_OFFER_SUBTITLE)
        if sub.count():
            return re.sub(r"\s+", " ", sub.first.inner_text()).strip()
        return ""

    def membership_popup_benefits(self) -> list[str]:
        """弹窗里的权益文案列表（线上 class：__benefit-label / __benefit-value）。"""
        popup = self.page.locator(SEL_OFFER)
        if not popup.count():
            return []
        labels = popup.first.locator(SEL_OFFER_BENEFIT_LABEL)
        out = [
            re.sub(r"\s+", " ", labels.nth(i).inner_text()).strip()
            for i in range(labels.count())
        ]
        if out:
            return out
        # 回退：整段权益区文本按行拆分
        block = popup.first.locator(SEL_OFFER_BENEFITS)
        if block.count():
            return [
                line.strip()
                for line in block.first.inner_text().splitlines()
                if line.strip()
            ]
        return []

    def membership_popup_button_text(self) -> str:
        """弹窗主按钮文案（线上 class：__cta）。"""
        cta = self.page.locator(SEL_OFFER_CTA)
        if cta.count():
            return re.sub(r"\s+", " ", cta.first.inner_text()).strip()
        return ""

    def click_popup_cta(self) -> None:
        """点击弹窗主按钮（Join for ...）。"""
        cta = self.page.locator(SEL_OFFER_CTA).first
        expect(cta).to_be_visible(timeout=TIMEOUT_UI_RENDER)
        cta.click()

    def _offer_blocks_interaction(self) -> bool:
        """会员 offer 弹窗是否仍在拦截点击。

        只看 __close 的可见性不够：点一次后弹窗可能重新渲染，
        __content 层还会继续 intercepts pointer events（2026-09-20 实测）。
        """
        return bool(
            self.page.evaluate(
                """(sel) => {
                    const offer = document.querySelector(sel);
                    if (!offer) return false;
                    if (!offer.offsetParent) return false;
                    const style = getComputedStyle(offer);
                    if (style.display === 'none' || style.visibility === 'hidden') {
                        return false;
                    }
                    return offer.getBoundingClientRect().height > 0;
                }""",
                SEL_OFFER,
            )
        )

    def close_membership_popup(self, *, observe_timeout: int = 0) -> None:
        """关闭会员 offer 弹窗，确认它不再拦截点击。

        必须能等：弹窗在页面加载后约 9 秒才渲染（2026-09-20 实测，
        domcontentloaded 后 900px 高的遮罩才挂上）。不等就立刻检查会看到
        高度 0，误判成"没有弹窗"直接返回，等到点 Get 时它才出现，
        于是报 __content intercepts pointer events 的 click timeout。

        observe_timeout > 0 时先观察这么久，等弹窗出现；已经出现则立即关。
        绝不改样式或删 DOM 绕过，只点真实关闭按钮。
        """
        deadline = time.monotonic() + max(0, observe_timeout) / 1000
        while not self._offer_blocks_interaction() and time.monotonic() < deadline:
            self.page.wait_for_timeout(200)
        for _ in range(3):
            if not self._offer_blocks_interaction():
                return
            close = self.page.locator(SEL_OFFER_CLOSE).first
            if not close.count():
                return
            try:
                close.click(timeout=3_000)
            except PlaywrightError:
                # 关闭按钮被上层遮住时稍等后重试，让主题脚本完成渲染。
                self.page.wait_for_timeout(500)
                continue
            self.page.wait_for_timeout(800)

    # ---- Generate 超限 toast ----

    def generate_limit_toast_text(self) -> str:
        """Generate 超限 toast 的文案。"""
        toast = self.page.locator(
            "[class*='toast'], [class*='notification'], [class*='alert'], [role='alert']"
        ).filter(has_text=re.compile(r"Daily limit|limit reached", re.I))
        if toast.count():
            return toast.first.inner_text().strip()
        return ""
