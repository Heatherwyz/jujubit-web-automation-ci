"""_click_visible_control 注入脚本的真实浏览器判定测试。

Python 侧的重试与派发由 test_click_visible_control.py 覆盖；这里覆盖注入 JS 的
判定本身——唯一性、禁用、遮挡、视口内外，以及"已渲染但不在视口"要先滚动而不是
直接报错。这些是最容易写错的部分：遮挡判断依赖 elementFromPoint，视口判断依赖
getBoundingClientRect，只有真实浏览器能验证。

启动 Chromium 需要几秒，因此这些用例比其余离线单测慢，但仍不访问任何网站。
"""

from __future__ import annotations

import inspect
import re
import unittest

from python_playwright.pages.cart_page import IS_RENDERED_JS, CartPage


def _injected_script() -> str:
    """取出 _click_visible_control 内联的 JS，并完成占位符替换。"""
    source = inspect.getsource(CartPage._click_visible_control)
    match = re.search(r'r"""(params => \{.*?)"""', source, re.S)
    if not match:  # pragma: no cover - 结构变更时立刻失败
        raise AssertionError("未能从 _click_visible_control 提取注入脚本")
    return match.group(1).replace("__IS_RENDERED__", IS_RENDERED_JS)


SCRIPT = _injected_script()

PAGE_TEMPLATE = """<!doctype html><html><head><style>
  body {{ margin: 0; font-family: sans-serif; }}
  .btn {{ width: 160px; height: 40px; display: block; }}
</style></head><body>{body}</body></html>"""


class _Browser:
    """整个测试类共用一个 Chromium，避免每条用例重启浏览器。"""

    playwright = None
    browser = None

    @classmethod
    def start(cls):
        from playwright.sync_api import sync_playwright

        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def stop(cls):
        if cls.browser:
            cls.browser.close()
        if cls.playwright:
            cls.playwright.stop()


class InjectedScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _Browser.start()

    @classmethod
    def tearDownClass(cls) -> None:
        _Browser.stop()

    def _evaluate(self, body: str, *, selector: str, exact_text: str = ""):
        page = _Browser.browser.new_page(viewport={"width": 800, "height": 600})
        try:
            page.set_content(PAGE_TEMPLATE.format(body=body))
            return page.evaluate(
                SCRIPT,
                {
                    "selector": selector,
                    "exactText": exact_text,
                    "description": "测试控件",
                },
            )
        finally:
            page.close()

    def test_unique_visible_button_reports_centre(self) -> None:
        result = self._evaluate(
            '<button class="btn">Add to Cart</button>', selector="button"
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["matchCount"], 1)
        # 160x40 的按钮位于左上角，中心应在 (80, 20) 附近。
        self.assertAlmostEqual(result["x"], 80, delta=2)
        self.assertAlmostEqual(result["y"], 20, delta=2)

    def test_exact_text_filters_same_selector(self) -> None:
        """2D/3D/Add to Cart 共用 'main button' 选择器，靠精确文案区分。"""
        body = (
            '<button class="btn">2D</button>'
            '<button class="btn">3D</button>'
            '<button class="btn">Add to Cart</button>'
        )

        result = self._evaluate(body, selector="button", exact_text="3D")

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["matchCount"], 1)

    def test_multiple_matches_are_rejected(self) -> None:
        """选择器命中多个控件时不能任选一个点击。"""
        body = '<button class="btn">Buy</button><button class="btn">Buy</button>'

        result = self._evaluate(body, selector="button", exact_text="Buy")

        self.assertFalse(result["ok"])
        self.assertEqual(result["matchCount"], 2)

    def test_no_match_reports_zero(self) -> None:
        result = self._evaluate('<div class="btn">not a button</div>', selector="button")

        self.assertFalse(result["ok"])
        self.assertEqual(result["matchCount"], 0)

    def test_disabled_button_is_rejected(self) -> None:
        result = self._evaluate(
            '<button class="btn" disabled>Add to Cart</button>', selector="button"
        )

        self.assertFalse(result["ok"])
        self.assertIn("禁用", result["reason"])

    def test_aria_disabled_button_is_rejected(self) -> None:
        """主题常用 aria-disabled 而非 disabled 属性表达不可用。"""
        result = self._evaluate(
            '<button class="btn" aria-disabled="true">Add to Cart</button>',
            selector="button",
        )

        self.assertFalse(result["ok"])
        self.assertIn("禁用", result["reason"])

    def test_hidden_button_is_not_counted(self) -> None:
        """display:none 的响应式副本不能被当成候选控件。"""
        body = (
            '<button class="btn" style="display:none">Add to Cart</button>'
            '<button class="btn">Add to Cart</button>'
        )

        result = self._evaluate(body, selector="button", exact_text="Add to Cart")

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["matchCount"], 1)

    def test_button_hidden_by_parent_opacity_is_not_counted(self) -> None:
        """父级 opacity:0 的副本同样不可点击；这是共享 isRendered 的关键场景。"""
        body = (
            '<div style="opacity:0">'
            '<button class="btn">Add to Cart</button></div>'
            '<button class="btn">Add to Cart</button>'
        )

        result = self._evaluate(body, selector="button", exact_text="Add to Cart")

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["matchCount"], 1)

    def test_obstructed_button_reports_blocker(self) -> None:
        """被遮挡时必须报出遮挡元素，便于定位是哪个浮层挡住了。"""
        body = (
            '<button class="btn">Add to Cart</button>'
            '<h2 id="overlay" class="jjb-banner__title" '
            'style="position:fixed;left:0;top:0;width:400px;height:200px;'
            'background:#fff;margin:0">Banner</h2>'
        )

        result = self._evaluate(body, selector="button", exact_text="Add to Cart")

        self.assertFalse(result["ok"])
        self.assertIn("遮挡", result["reason"])
        self.assertIn("h2", result["blocker"])

    def test_button_below_fold_requests_reacquire_after_scrolling(self) -> None:
        """首屏之外的控件必须先滚动并要求重新定位，不能直接判失败。"""
        body = (
            '<div style="height:3000px"></div>'
            '<button class="btn">Add to Cart</button>'
        )

        result = self._evaluate(body, selector="button", exact_text="Add to Cart")

        self.assertFalse(result["ok"])
        self.assertTrue(result.get("reacquire"), result)
        self.assertEqual(result["matchCount"], 1)

    def test_reacquired_button_becomes_clickable_after_scroll(self) -> None:
        """模拟 Python 侧的第二轮：滚动后重新求值应当成功。"""
        page = _Browser.browser.new_page(viewport={"width": 800, "height": 600})
        try:
            page.set_content(
                PAGE_TEMPLATE.format(
                    body='<div style="height:3000px"></div>'
                    '<button class="btn">Add to Cart</button>'
                )
            )
            params = {
                "selector": "button",
                "exactText": "Add to Cart",
                "description": "测试控件",
            }
            first = page.evaluate(SCRIPT, params)
            self.assertTrue(first.get("reacquire"), first)

            second = page.evaluate(SCRIPT, params)

            self.assertTrue(second["ok"], second)
            self.assertGreaterEqual(second["y"], 0)
            self.assertLess(second["y"], 600)
        finally:
            page.close()

    def test_reported_coordinates_stay_inside_viewport(self) -> None:
        """坐标必须被夹紧在视口内，否则真实输入事件会落到页面外。"""
        body = (
            '<button class="btn" style="position:fixed;left:790px;top:590px">'
            "Add to Cart</button>"
        )

        result = self._evaluate(body, selector="button", exact_text="Add to Cart")

        if result["ok"]:
            self.assertGreaterEqual(result["x"], 0)
            self.assertGreaterEqual(result["y"], 0)
            self.assertLess(result["x"], 800)
            self.assertLess(result["y"], 600)

    def test_coarse_pointer_flag_is_reported(self) -> None:
        """该标志决定走 touchscreen.tap 还是 mouse.click。"""
        result = self._evaluate(
            '<button class="btn">Add to Cart</button>', selector="button"
        )

        self.assertIn("coarsePointer", result)
        self.assertIsInstance(result["coarsePointer"], bool)


if __name__ == "__main__":
    unittest.main()
