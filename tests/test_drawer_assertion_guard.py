"""抽屉断言不得因活动标记缺失而静默通过。

``CartPage.drawer`` 依赖 ``_refresh_active_drawer`` 打的
``data-jujubit-active-drawer`` 标记。标记失败时该 locator 命中 0 个元素，于是：

- ``expect(drawer).not_to_be_visible()`` 恒真——抽屉仍开着也算关闭成功；
- ``if drawer.is_visible():`` 恒假——整段 UI 一致性检查被跳过。

第二种尤其危险：``assert_page_integrity`` 正是用它核对"抽屉显示的数量与服务端
一致"，而这是 CART-15 要抓的缺陷。用真实 DOM 验证过：抽屉开着且含商品节点时，
标记缺失会让检查完全不执行。
"""

from __future__ import annotations

import unittest

from python_playwright.pages.cart_page import CartPage


class _Page:
    """只实现断言路径用到的 evaluate / wait_for_timeout。"""

    def __init__(self, open_count: int):
        self.open_count = open_count
        self.waits = 0

    def evaluate(self, script, *args):
        return self.open_count

    def wait_for_timeout(self, _ms):
        self.waits += 1


def _cart(open_count: int) -> CartPage:
    cart = object.__new__(CartPage)
    cart.page = _Page(open_count)
    cart.base_url = "https://jujubit.ai"
    return cart


class OpenDrawerCountTests(unittest.TestCase):
    def test_reports_zero_when_no_drawer_is_open(self) -> None:
        self.assertEqual(_cart(0)._open_drawer_count(), 0)

    def test_reports_actual_count_independent_of_marker(self) -> None:
        """计数走真实选择器，不读活动标记，因此标记缺失也能发现抽屉。"""
        self.assertEqual(_cart(2)._open_drawer_count(), 2)

    def test_evaluate_failure_is_treated_as_not_open(self) -> None:
        from playwright.sync_api import Error as PlaywrightError

        class _Failing(_Page):
            def evaluate(self, script, *args):
                raise PlaywrightError("Execution context was destroyed")

        cart = object.__new__(CartPage)
        cart.page = _Failing(1)
        cart.base_url = "https://jujubit.ai"

        self.assertEqual(cart._open_drawer_count(), 0)


class AssertNoOpenDrawerTests(unittest.TestCase):
    def test_passes_once_no_drawer_remains(self) -> None:
        _cart(0)._assert_no_open_drawer(timeout=1_000)

    def test_raises_when_a_drawer_is_still_open(self) -> None:
        """这是原先恒真的那条断言，现在必须真的失败。"""
        with self.assertRaisesRegex(AssertionError, "未在限定时间内关闭"):
            _cart(1)._assert_no_open_drawer(timeout=300)

    def test_failure_message_reports_remaining_count(self) -> None:
        with self.assertRaises(AssertionError) as caught:
            _cart(3)._assert_no_open_drawer(timeout=300)

        self.assertIn("3", str(caught.exception))


class DrawerCountUsesSharedVisibilityTests(unittest.TestCase):
    """计数脚本必须复用统一的 isRendered，而不是再写一份判定。"""

    def test_script_injects_shared_helper(self) -> None:
        import inspect

        source = inspect.getsource(CartPage._open_drawer_count)

        self.assertIn("IS_RENDERED_JS", source)
        self.assertIn(".ccd.is-open", source)
        # 不能自己再定义一份判定逻辑。
        self.assertNotIn("getComputedStyle", source)


if __name__ == "__main__":
    unittest.main()
