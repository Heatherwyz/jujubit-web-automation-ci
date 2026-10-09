"""Edit 生成入口自动化。

实验由调用方显式注入，不在页面对象里修改站点运行模式。入口出现后
不点击 Edit，避免建立长连接或创建生成任务。
"""

import json

from playwright.sync_api import Page, expect

from python_playwright.pages.home_page import HomePage


class EditGenerationPage:
    """创作页 Edit 入口。"""

    PATH = "/products/customize-your-own"

    def __init__(self, page: Page, home: HomePage):
        self.page = page
        self.home = home

    def enable_experiment(self) -> None:
        """按确认过的 Statsig 覆盖值开启 edit_generation。"""
        self.home.open(self.PATH)
        self.page.evaluate(
            """() => localStorage.setItem(
                '_statsig_override',
                JSON.stringify({edit_generation: {enable: true}})
            )"""
        )
        self.page.reload(wait_until="domcontentloaded", timeout=45_000)
        self.home.close_welcome_popup()

    def open_gallery(self) -> None:
        """打开已有资产列表；实验值必须仍保留。"""
        stored = self.page.evaluate("() => localStorage.getItem('_statsig_override')")
        assert json.loads(stored or "{}").get("edit_generation", {}).get("enable") is True
        self.page.get_by_role("button", name="Gallery").click()

    def edit_button(self):
        """当前已完成资产上的 Edit 入口。"""
        return self.page.get_by_role("button", name="Edit")
