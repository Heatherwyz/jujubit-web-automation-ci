"""Inspiration / SHOWCASE 页面对象。

只封装当前已上线、可稳定观察的行为：导航入口、分区接口和作品卡。
购买、结账和 Remix 会改变购物车或创建生成记录，不放在这里自动执行。
"""

import re

from playwright.sync_api import Error as PlaywrightError, Page, expect

from python_playwright.pages.home_page import HomePage


class InspirationNotLaunchedError(RuntimeError):
    """当前访问者看不到 Inspiration，功能尚未放开。"""


class InspirationPage:
    """社区 Inspiration 的可复用操作。"""

    TAB_LIST_PATH = "/apps/ai/inspiration-tab-list"
    FEED_LIST_PATH = "/apps/ai/inspiration-list"

    def __init__(self, page: Page, home: HomePage):
        self.page = page
        self.home = home

    def open_from_navigation(self) -> None:
        """从当前端导航进入 Inspiration；入口不存在时明确标为未上线。"""
        self.home.close_welcome_popup()
        entry = self._entry_link()
        if entry.count() == 0:
            raise InspirationNotLaunchedError(
                "当前页面没有 Inspiration 导航入口，社区功能未对本次访问放开。"
            )
        expect(entry).to_be_visible()
        entry.click()
        self.page.wait_for_function(
            "document.readyState !== 'loading'",
            timeout=30_000,
        )

    def _entry_link(self):
        """返回当前视口里真正可见的 Inspiration 链接。"""
        if self._is_h5():
            self.home.open_h5_menu()
            scope = self.page.locator("#JjbMobileDrawer")
        else:
            scope = self.home.primary_nav
        return scope.get_by_role("link", name=re.compile(r"^inspiration$", re.I))

    def _is_h5(self) -> bool:
        return self.page.viewport_size["width"] < 768

    def visible_tabs(self) -> list[dict]:
        """读取用户当前能看到的分区，并排除技术文档要求隐藏的 campaign。"""
        tabs = self.page.locator("[role='tab'], [data-inspiration-tab-id]")
        result = tabs.evaluate_all(
            """(nodes) => nodes.filter((node) => {
                const style = getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden'
                    && rect.width > 0 && rect.height > 0;
            }).map((node) => ({
                id: node.getAttribute('data-inspiration-tab-id')
                    || node.getAttribute('data-tab-id') || '',
                name: (node.innerText || '').replace(/\\s+/g, ' ').trim(),
                selected: node.getAttribute('aria-selected') === 'true'
                    || node.classList.contains('is-active'),
            }))"""
        )
        return [
            tab for tab in result
            if tab["name"] and not re.search(r"campaign", tab["id"] + tab["name"], re.I)
        ]

    def feed_cards(self):
        """返回作品卡；页面若尚未提供稳定标记，则退到 Showcase 卡片结构。"""
        return self.page.locator(
            "[data-inspiration-post-id], [data-post-id], .jjb-showcase__card"
        )

    def capture_feed_requests(self) -> list[dict]:
        """读取本次页面已经发出的 Inspiration 接口，供分页和分区断言使用。"""
        requests = self.page.evaluate(
            """(paths) => performance.getEntriesByType('resource')
                .map((entry) => entry.name)
                .filter((url) => paths.some((path) => url.includes(path)))""",
            [self.TAB_LIST_PATH, self.FEED_LIST_PATH],
        )
        return [{"url": url} for url in requests]

    def assert_feed_loaded(self) -> None:
        """首屏至少展示一张作品卡，或展示明确的空状态。"""
        cards = self.feed_cards()
        empty = self.page.get_by_text(re.compile(r"no inspiration|nothing to show|暂无", re.I))
        expect(cards.or_(empty).first).to_be_visible(timeout=15_000)

    def card_price_text(self, card) -> str:
        """读取单张作品卡上的价格文案。"""
        return card.inner_text()

    def open_detail_from_card(self, card) -> None:
        """点击作品封面，不点价格或购物车等操作区。"""
        image = card.locator("img").first
        image.click()

    def add_to_cart_from_card(self, card) -> None:
        """点击作品卡内的购物车操作，验证不会冒泡成详情。"""
        trigger = card.get_by_role("button", name=re.compile(r"cart|add", re.I))
        if trigger.count() == 0:
            trigger = card.locator("[data-action='add-to-cart'], .icon-cart").first
        trigger.click()

    def detail_root(self):
        """作品详情弹层或纵向详情区域。"""
        return self.page.locator("[data-inspiration-detail], [role='dialog']").last

    def sku_root(self):
        """SKU 区域；购买动作由调用方决定是否执行。"""
        return self.page.locator("[data-inspiration-sku], form[action*='/cart/add']").last

    def assert_no_backend_error(self) -> None:
        """接口失败时不能把后端堆栈直接展示给用户。"""
        body = self.page.locator("body").inner_text(timeout=5_000)
        assert not re.search(r"traceback|exception|stack trace", body, re.I)

    def safe_text(self, locator) -> str:
        """元素在动画中被替换时返回空字符串，由用例决定是否重试。"""
        try:
            return locator.inner_text(timeout=3_000)
        except PlaywrightError:
            return ""
