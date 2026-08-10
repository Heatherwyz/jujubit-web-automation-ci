"""购物车生成结果等待逻辑的离线回归测试。"""

import unittest

from python_playwright.pages.cart_page import CartPage


class _ImageLocator:
    """返回选择器对应的模拟图片地址。"""

    def __init__(self, image_url: str):
        self.image_url = image_url

    def evaluate_all(self, _script: str) -> str:
        return self.image_url


class _ModelButtonLocator:
    """模拟 3D 按钮由禁用到解锁的 class 与属性。"""

    def __init__(self, ready: bool):
        self.ready = ready
        self.first = self

    def filter(self, **_kwargs):
        return self

    def count(self) -> int:
        return 1

    def get_attribute(self, name: str):
        if name == "class":
            return "text-[#fe5a12]" if self.ready else "opacity-50 cursor-not-allowed"
        return None


class _ImagePage:
    """只实现 2D 图片检查所需的最小 Page 接口。"""

    def __init__(self, hidden_image_url: str = "", model_ready: bool = False):
        self.hidden_image_url = hidden_image_url
        self.model_ready = model_ready
        self.selectors = []

    def locator(self, selector: str):
        self.selectors.append(selector)
        if selector == "#jjb-create-canvas button:visible":
            return _ModelButtonLocator(self.model_ready)
        # 模拟前端自动切到 3D：图片已加载，但带 :visible 的查询无法找到它。
        image_url = "" if ":visible" in selector else self.hidden_image_url
        return _ImageLocator(image_url)

    def evaluate(self, _script: str) -> bool:
        # 回归测试走“渲染器封装、按钮解锁”的线上兼容分支。
        return False


class CartGeneratedImageTests(unittest.TestCase):
    """保证 2D 面板被隐藏时不会把已加载图片误报为超时。"""

    def _cart(self, page: _ImagePage) -> CartPage:
        cart = object.__new__(CartPage)
        cart.page = page
        return cart

    def test_loaded_image_in_hidden_2d_panel_is_accepted(self) -> None:
        page = _ImagePage("https://cdn.jujubit.ai/generated/result.png")

        loaded = self._cart(page)._generated_image_loaded()

        self.assertTrue(loaded)
        self.assertEqual(page.selectors, ['[data-view-name="2d"] img'])

    def test_missing_2d_image_is_not_reported_as_loaded(self) -> None:
        page = _ImagePage()

        loaded = self._cart(page)._generated_image_loaded()

        self.assertFalse(loaded)

    def test_unlocked_3d_control_is_reported_as_ready(self) -> None:
        page = _ImagePage(model_ready=True)

        loaded = self._cart(page)._generated_model_loaded()

        self.assertTrue(loaded)

    def test_locked_3d_control_is_not_reported_as_ready(self) -> None:
        page = _ImagePage(model_ready=False)

        loaded = self._cart(page)._generated_model_loaded()

        self.assertFalse(loaded)


if __name__ == "__main__":
    unittest.main()
