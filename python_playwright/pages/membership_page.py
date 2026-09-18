"""会员页面对象：付费墙、Membership 管理页、弹窗、Banner、支付拉起。

设计原则：
- 支付走到拉起即止（Airwallex 半屏/全屏支付表单可见），不填卡不付款。
- 复用 HomePage 的弹窗关闭、限速、登录态检查。
- 实验开关注入从提测单获取的 Statsig 方式。
"""

from __future__ import annotations

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

# 管理页 Tab 顺序
PROFILE_TAB_ORDER = ("PROFILE", "ORDERS", "MEMBERSHIP")

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
        """从个人中心进入 Membership 管理页。"""
        self.home.close_welcome_popup()
        tab = self.page.locator(
            'a[href*="membership"], button:has-text("MEMBERSHIP")'
        ).first
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
        """切换 Monthly / Yearly。线上是 .jjb-membership-paywall__toggle 内的按钮。"""
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
        """点击指定档位的 Get/Upgrade 按钮。"""
        self.home.close_popup_before_click()
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

    def wait_for_payment_form(self, timeout: int = TIMEOUT_SDK_LOAD) -> None:
        """等待半屏支付表单（Airwallex SDK）加载完成。

        断言边界：弹窗出现 → loading 消失 → SDK 挂载点有内容。
        不填卡、不点 Pay Now、不产生真实扣款。
        """
        # 1) 半屏弹窗容器必须先出现
        try:
            self.page.wait_for_selector(SEL_CHECKOUT, timeout=timeout // 3)
        except PlaywrightTimeoutError:
            raise AssertionError(
                f"半屏支付弹窗未出现（选择器 {SEL_CHECKOUT}）"
            ) from None

        # 2) 等 SDK 挂载：loading 消失或 mount/form-host 内出现 iframe
        deadline = time.monotonic() + timeout / 1000
        last_state = "未知"
        while time.monotonic() < deadline:
            state = self.page.evaluate(
                """([selMount, selHost, selLoading]) => {
                    const mount = document.querySelector(selMount);
                    const host = document.querySelector(selHost);
                    const loading = document.querySelector(selLoading);
                    const loadingVisible = loading
                        && getComputedStyle(loading).display !== 'none'
                        && loading.offsetHeight > 0;
                    const frames = document.querySelectorAll(
                        '.jjb-membership-checkout iframe'
                    ).length;
                    return {
                        hasMount: Boolean(mount),
                        mountChildren: mount ? mount.children.length : -1,
                        hasHost: Boolean(host),
                        loadingVisible: Boolean(loadingVisible),
                        frames,
                    };
                }""",
                [SEL_CHECKOUT_MOUNT, SEL_CHECKOUT_FORM_HOST, SEL_CHECKOUT_LOADING],
            )
            last_state = str(state)
            # SDK 就绪的判定：出现 iframe，或挂载点已有子节点且 loading 已消失
            if state.get("frames", 0) > 0:
                return
            if state.get("mountChildren", 0) > 0 and not state.get("loadingVisible"):
                return
            self.page.wait_for_timeout(500)

        raise AssertionError(
            f"半屏支付表单未在 {timeout}ms 内加载完成，最后状态：{last_state}"
        )

    def payment_plan_label(self) -> str:
        """半屏支付弹窗里的套餐标签，如 'Pro Membership · Monthly'。"""
        plan = self.page.locator(SEL_CHECKOUT_PLAN)
        if plan.count():
            return re.sub(r"\s+", " ", plan.first.inner_text()).strip()
        return ""

    def payment_billing_label(self) -> str:
        """支付弹窗里的账期说明，如 'Billed monthly, starting ...'。"""
        label = self.page.locator(SEL_CHECKOUT_BILLING_LABEL)
        if label.count():
            return re.sub(r"\s+", " ", label.first.inner_text()).strip()
        return ""

    def payment_amount_text(self) -> str:
        """半屏支付弹窗里的实付金额文案。"""
        for sel in (SEL_CHECKOUT_PRICE, SEL_CHECKOUT_SUBTOTAL):
            node = self.page.locator(sel)
            if node.count():
                text = re.sub(r"\s+", " ", node.first.inner_text()).strip()
                if re.search(r"[\d.]+", text):
                    return text
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
        """支付弹窗内的 iframe 数量——SDK 已挂载的直接证据。"""
        return self.page.locator(f"{SEL_CHECKOUT} iframe").count()

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
        """关闭半屏支付弹窗。不提交任何支付信息。"""
        close = self.page.locator(SEL_CHECKOUT_CLOSE).first
        if close.count() and close.is_visible():
            close.click()
            self.page.wait_for_timeout(1000)

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
        """个人中心的 Tab 文案列表。"""
        tabs = self.page.locator(
            "[class*='tab'], [role='tab'], nav a, nav button"
        ).filter(has_text=re.compile(r"PROFILE|ORDERS|MEMBERSHIP", re.I))
        return [tabs.nth(i).inner_text().strip().upper() for i in range(tabs.count())]

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

    def billing_history_text(self) -> str:
        """Billing History 区域的文案（含空态）。"""
        section = self.page.locator(
            "[class*='billing'], [class*='history']"
        ).filter(has_text=re.compile(r"billing|history", re.I))
        if section.count():
            return section.first.inner_text().strip()
        return ""

    # ---- 引流 Banner ----

    def banner_text(self, page_name: str = "") -> str:
        """当前页面的会员引流 banner 文案。"""
        banner = self.page.locator(
            "[class*='membership-banner'], [class*='vip-banner'], [class*='upgrade-banner']"
        )
        if banner.count():
            return banner.first.inner_text().strip()
        # 回退：搜含 Members 文案的区域
        members = self.page.locator(":has-text('Members')").filter(
            has_text=re.compile(r"Members\s*(save|:)", re.I)
        )
        if members.count():
            return members.first.inner_text().strip()
        return ""

    def banner_visible(self) -> bool:
        """会员引流 banner 是否可见。"""
        return bool(self.banner_text())

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

    def close_membership_popup(self) -> None:
        """关闭会员弹窗（线上 class：__close）。"""
        close = self.page.locator(SEL_OFFER_CLOSE).first
        if close.count() and close.is_visible():
            close.click()
            self.page.wait_for_timeout(600)

    # ---- Generate 超限 toast ----

    def generate_limit_toast_text(self) -> str:
        """Generate 超限 toast 的文案。"""
        toast = self.page.locator(
            "[class*='toast'], [class*='notification'], [class*='alert'], [role='alert']"
        ).filter(has_text=re.compile(r"Daily limit|limit reached", re.I))
        if toast.count():
            return toast.first.inner_text().strip()
        return ""
