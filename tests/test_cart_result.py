"""购物车生成结果等待逻辑的离线回归测试。"""

import unittest

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


if __name__ == "__main__":
    unittest.main()
