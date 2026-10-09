"""万圣节专题页对象。

页面地址固定为 /pages/halloween-special。这里只读取当前已发布内容，
不进入后台改配置，也不点击 Generate，避免创建真实生成任务。
"""

import re

from playwright.sync_api import Page, expect

from python_playwright.pages.home_page import HomePage


class HalloweenPage:
    """万圣节专题页可复用定位。"""

    PATH = "/pages/halloween-special"

    def __init__(self, page: Page, home: HomePage):
        self.page = page
        self.home = home

    def open(self) -> None:
        """打开专题页并关闭可能延迟出现的优惠弹窗。"""
        self.home.open(self.PATH)
        self.home.close_welcome_popup()
        expect(self.page.locator("main")).to_be_visible()

    def banner(self):
        """首个有内容的活动 Banner。"""
        return self.page.locator(".jjb-banner").filter(
            has_text=re.compile(r"Halloween Collection", re.I)
        ).first

    def style_cards(self):
        """Explore Your Style 中配置了跳转链接的风格卡。"""
        return self.page.locator(".jjb-activity-category a[href]")

    def creator(self):
        """专题页内嵌的创作区，不点击 Generate。"""
        return self.page.locator(".jjb-page-canvas-section, #jjb-page-canvas-section").first

    def products(self):
        """Trendy Products 中进入商品详情的链接。"""
        return self.page.locator(".jjb-activity-products a[href*='/products/']")

    def row_count(self, locator) -> int:
        """按可见卡片顶部位置计算行数，容许同一行 20px 内的渲染误差。"""
        tops = locator.evaluate_all(
            """(nodes) => nodes
                .map((node) => Math.round(node.getBoundingClientRect().top))
                .filter((top) => top > 0)
                .sort((a, b) => a - b)"""
        )
        rows = 0
        previous = None
        for top in tops:
            if previous is None or abs(top - previous) > 20:
                rows += 1
                previous = top
        return rows
