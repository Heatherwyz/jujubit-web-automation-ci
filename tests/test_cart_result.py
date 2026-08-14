"""购物车生成结果等待逻辑的离线回归测试。"""

import unittest
from unittest.mock import Mock

from python_playwright.pages.cart_page import CartPage


class _ImageLocator:
    """返回选择器对应的模拟图片地址。"""

    def __init__(self, image_url: str):
        self.image_url = image_url

    def evaluate_all(self, _script: str) -> str:
        return self.image_url


class _CountLocator:
    """只提供资源就绪判断需要的 count。"""

    def __init__(self, count: int):
        self._count = count

    def count(self) -> int:
        return self._count


class _ModelViewLocator(_CountLocator):
    """模拟当前可见 3D 面板中的 Loading 文案和 canvas。"""

    def __init__(self, *, visible: bool, loading: bool, canvas_visible: bool):
        super().__init__(int(visible))
        self.first = self
        self.loading = loading
        self.canvas_visible = canvas_visible

    def get_by_text(self, _text: str, *, exact: bool):
        return _CountLocator(int(self.loading and exact))

    def locator(self, selector: str):
        assert selector == "canvas:visible"
        return _CountLocator(int(self.canvas_visible))


class _ResultPage:
    """只实现 2D/3D 结果检查所需的最小 Page 接口。"""

    def __init__(
        self,
        hidden_image_url: str = "",
        *,
        model_view_visible: bool = True,
        model_loading: bool = False,
        model_canvas_visible: bool = False,
    ):
        self.hidden_image_url = hidden_image_url
        self.model_view_visible = model_view_visible
        self.model_loading = model_loading
        self.model_canvas_visible = model_canvas_visible
        self.selectors = []

    def locator(self, selector: str):
        self.selectors.append(selector)
        if selector == '[data-view-name="3d"]:visible':
            return _ModelViewLocator(
                visible=self.model_view_visible,
                loading=self.model_loading,
                canvas_visible=self.model_canvas_visible,
            )
        # 模拟前端自动切到 3D：图片已加载，但带 :visible 的查询无法找到它。
        image_url = "" if ":visible" in selector else self.hidden_image_url
        return _ImageLocator(image_url)


class CartGeneratedResultTests(unittest.TestCase):
    """保证已完成的 2D/3D 资源不会被误报，加载中资源不会抢跑。"""

    def _cart(self, page: _ResultPage) -> CartPage:
        cart = object.__new__(CartPage)
        cart.page = page
        return cart

    def test_loaded_image_in_hidden_2d_panel_is_accepted(self) -> None:
        page = _ResultPage("https://cdn.jujubit.ai/generated/result.png")

        loaded = self._cart(page)._generated_image_loaded()

        self.assertTrue(loaded)
        self.assertEqual(page.selectors, ['[data-view-name="2d"] img'])

    def test_missing_2d_image_is_not_reported_as_loaded(self) -> None:
        page = _ResultPage()

        loaded = self._cart(page)._generated_image_loaded()

        self.assertFalse(loaded)

    def test_visible_3d_canvas_is_reported_as_ready(self) -> None:
        page = _ResultPage(model_canvas_visible=True)

        loaded = self._cart(page)._generated_model_loaded()

        self.assertTrue(loaded)

    def test_splat_canvas_waits_for_loading_overlay_to_disappear(self) -> None:
        page = _ResultPage(model_canvas_visible=True, model_loading=True)

        loaded = self._cart(page)._generated_model_loaded()

        self.assertFalse(loaded)

    def test_hidden_3d_view_is_not_reported_as_ready(self) -> None:
        page = _ResultPage(
            model_view_visible=False,
            model_canvas_visible=True,
        )

        loaded = self._cart(page)._generated_model_loaded()

        self.assertFalse(loaded)

    def test_missing_3d_renderer_is_not_reported_as_ready(self) -> None:
        page = _ResultPage()

        loaded = self._cart(page)._generated_model_loaded()

        self.assertFalse(loaded)

    def test_dom_click_requires_one_visible_enabled_uncovered_control(self) -> None:
        """CI 点击仍要经过唯一性、禁用态和遮挡检查，并发送真实输入事件。"""
        page = Mock()
        page.evaluate.return_value = {
            "ok": True,
            "x": 120,
            "y": 240,
            "coarsePointer": True,
        }
        cart = self._cart(page)

        cart._click_visible_control(
            "#jjb-create-canvas button",
            description="点击 Add to Cart",
            exact_text="Add to Cart",
        )

        page.evaluate.assert_called_once()
        script, params = page.evaluate.call_args.args
        self.assertIn("elementFromPoint", script)
        self.assertNotIn("element.click()", script)
        self.assertNotIn("requestAnimationFrame", script)
        self.assertNotIn("hit.contains(element)", script)
        self.assertEqual(params["exactText"], "Add to Cart")
        page.touchscreen.tap.assert_called_once_with(120, 240)
        page.mouse.click.assert_not_called()

    def test_desktop_control_uses_real_mouse_click(self) -> None:
        page = Mock()
        page.evaluate.return_value = {
            "ok": True,
            "x": 600,
            "y": 80,
            "coarsePointer": False,
        }
        cart = self._cart(page)

        cart._click_visible_control(
            ".jjb-header__cart",
            description="点击 Header Cart",
        )

        page.mouse.click.assert_called_once_with(600, 80)
        page.touchscreen.tap.assert_not_called()

    def test_dom_click_surfaces_page_blocker_in_chinese(self) -> None:
        page = Mock()
        page.evaluate.return_value = {
            "ok": False,
            "reason": "控件中心被其他元素遮挡",
            "blocker": "div.newsletter-popup-v2__overlay",
        }
        cart = self._cart(page)

        with self.assertRaisesRegex(
            AssertionError,
            "控件中心被其他元素遮挡.*newsletter-popup-v2__overlay",
        ):
            cart._click_visible_control(
                ".jjb-header__cart",
                description="点击 Header Cart",
            )

        page.mouse.click.assert_not_called()
        page.touchscreen.tap.assert_not_called()

    def test_result_view_click_covers_pc_portal_and_h5_root(self) -> None:
        """2D/3D 点击同时覆盖 PC Portal 与 H5 Creator，且只调用一次点击助手。"""
        page = Mock()
        cart = self._cart(page)
        cart.home = Mock()
        cart._click_visible_control = Mock()

        cart._select_result_view("2D")

        cart.home.close_popup_before_click.assert_called_once_with()
        cart._click_visible_control.assert_called_once_with(
            "#jjb-create-canvas button, "
            ".product-image-container > .jjb-app button",
            description="切换到 2D 结果",
            exact_text="2D",
        )

    def test_checkout_summary_uses_visible_order_summary_button(self) -> None:
        """按钮名称只有 Order summary 时，也应跳过隐藏副本并展开可见摘要。"""
        page = Mock()
        title_locator = Mock()
        title_locator.all.return_value = []
        page.get_by_text.return_value = title_locator
        hidden_toggle = Mock()
        hidden_toggle.is_visible.return_value = False
        visible_toggle = Mock()
        visible_toggle.is_visible.return_value = True
        visible_toggle.get_attribute.return_value = "false"
        toggles = Mock()
        toggles.all.return_value = [hidden_toggle, visible_toggle]
        page.get_by_role.return_value = toggles
        cart = self._cart(page)

        cart._expand_checkout_summary("JuJuBit product")

        role, = page.get_by_role.call_args.args
        self.assertEqual(role, "button")
        self.assertRegex("Order summary", page.get_by_role.call_args.kwargs["name"])
        hidden_toggle.click.assert_not_called()
        visible_toggle.click.assert_called_once_with(no_wait_after=True)

    def test_checkout_summary_does_not_collapse_visible_product(self) -> None:
        """商品标题已经可见时不再点击摘要按钮，避免把展开内容重新折叠。"""
        page = Mock()
        visible_title = Mock()
        visible_title.is_visible.return_value = True
        title_locator = Mock()
        title_locator.all.return_value = [visible_title]
        page.get_by_text.return_value = title_locator
        cart = self._cart(page)

        cart._expand_checkout_summary("JuJuBit product")

        page.get_by_role.assert_not_called()

    def test_checkout_title_waits_for_expand_animation(self) -> None:
        """展开动画替换节点时会重新读取 DOM，直到标题真正可见。"""
        page = Mock()
        hidden_title = Mock()
        hidden_title.is_visible.return_value = False
        visible_title = Mock()
        visible_title.is_visible.return_value = True
        title_locator = Mock()
        title_locator.all.side_effect = [[hidden_title], [visible_title]]
        page.get_by_text.return_value = title_locator
        cart = self._cart(page)

        cart._wait_for_visible_exact_text("JuJuBit product", timeout=1_000)

        page.wait_for_timeout.assert_called_once_with(100)


if __name__ == "__main__":
    unittest.main()
