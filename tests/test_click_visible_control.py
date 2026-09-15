"""_click_visible_control 的离线回归测试。

这是购物车里最复杂、也最容易 flaky 的方法：既要处理 React Portal 重渲染导致的
节点替换，又要区分"已渲染"与"当前在视口内"，还要在遮挡、禁用、多重匹配时给出
可定位的失败原因。此前没有任何直接单测。

这里用假的 Page 驱动 Python 侧的重试与派发逻辑（不起浏览器）；注入 JS 的判定
逻辑由 test_click_visible_control_js.py 在真实浏览器里覆盖。
"""

from __future__ import annotations

import unittest

from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)

from python_playwright.pages.cart_page import CartPage


class _Mouse:
    def __init__(self):
        self.clicks: list[tuple[int, int]] = []

    def click(self, x, y):
        self.clicks.append((x, y))


class _Touchscreen:
    def __init__(self):
        self.taps: list[tuple[int, int]] = []

    def tap(self, x, y):
        self.taps.append((x, y))


class _Page:
    """按预设脚本依次返回 evaluate 结果，并记录点击派发。"""

    def __init__(self, results, *, url="https://jujubit.ai/products/x"):
        self._results = list(results)
        self.url = url
        self.mouse = _Mouse()
        self.touchscreen = _Touchscreen()
        self.evaluate_calls = 0
        self.waits = 0
        self.wait_for_function_calls = 0
        self._navigated_to = None

    def evaluate(self, script, params=None):
        self.evaluate_calls += 1
        if not self._results:
            raise AssertionError("evaluate 调用次数超出预设")
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def wait_for_timeout(self, _ms):
        self.waits += 1

    def wait_for_function(self, _script, arg=None, timeout=None):
        self.wait_for_function_calls += 1
        if self._navigated_to is None:
            raise PlaywrightTimeoutError("URL 未变化")
        self.url = self._navigated_to


def _cart(page: _Page) -> CartPage:
    cart = object.__new__(CartPage)
    cart.page = page
    cart.base_url = "https://jujubit.ai"
    return cart


def _ok(x=120, y=240, coarse=False) -> dict:
    return {"ok": True, "matchCount": 1, "x": x, "y": y, "coarsePointer": coarse}


class SuccessPathTests(unittest.TestCase):
    def test_mouse_click_is_dispatched_at_reported_centre(self) -> None:
        page = _Page([_ok(150, 300)])

        _cart(page)._click_visible_control("button", description="加购")

        self.assertEqual(page.mouse.clicks, [(150, 300)])
        self.assertEqual(page.touchscreen.taps, [])

    def test_coarse_pointer_uses_touch_tap(self) -> None:
        """H5 必须走真实触摸事件，鼠标点击在移动端主题上可能不触发处理器。"""
        page = _Page([_ok(80, 160, coarse=True)])

        _cart(page)._click_visible_control("button", description="加购")

        self.assertEqual(page.touchscreen.taps, [(80, 160)])
        self.assertEqual(page.mouse.clicks, [])

    def test_single_evaluate_when_first_attempt_succeeds(self) -> None:
        page = _Page([_ok()])

        _cart(page)._click_visible_control("button", description="加购")

        self.assertEqual(page.evaluate_calls, 1)
        self.assertEqual(page.waits, 0)


class ReacquireTests(unittest.TestCase):
    """Portal 替换节点后必须重新定位，且真实输入事件只发一次。"""

    def test_reacquire_retries_then_clicks_once(self) -> None:
        page = _Page(
            [
                {"ok": False, "matchCount": 1, "reacquire": True, "reason": "已滚动"},
                _ok(200, 400),
            ]
        )

        _cart(page)._click_visible_control("button", description="加购")

        self.assertEqual(page.evaluate_calls, 2)
        self.assertEqual(page.mouse.clicks, [(200, 400)], "点击只能派发一次")

    def test_zero_matches_is_treated_as_transient_and_retried(self) -> None:
        """0 个候选通常是 Portal 短暂卸载，不能立即判失败。"""
        page = _Page([{"ok": False, "matchCount": 0, "reason": "未找到"}, _ok()])

        _cart(page)._click_visible_control("button", description="加购")

        self.assertEqual(page.evaluate_calls, 2)
        self.assertEqual(len(page.mouse.clicks), 1)

    def test_persistent_reacquire_eventually_fails_with_reason(self) -> None:
        """一直重新定位不成功时必须失败，不能静默返回。"""
        page = _Page(
            [{"ok": False, "matchCount": 0, "reason": "控件始终未出现"}] * 21
        )

        with self.assertRaises(AssertionError) as caught:
            _cart(page)._click_visible_control("button", description="加购")

        self.assertIn("加购失败", str(caught.exception))
        self.assertIn("控件始终未出现", str(caught.exception))
        self.assertEqual(page.mouse.clicks, [], "失败时不得派发点击")

    def test_retry_budget_is_bounded(self) -> None:
        page = _Page([{"ok": False, "matchCount": 0, "reason": "x"}] * 21)

        with self.assertRaises(AssertionError):
            _cart(page)._click_visible_control("button", description="加购")

        self.assertEqual(page.evaluate_calls, 21, "重试次数必须有界")


class NonRetryableFailureTests(unittest.TestCase):
    """遮挡、禁用、多重匹配是确定性问题，立即失败并带出定位信息。"""

    def test_obstruction_fails_immediately_with_blocker(self) -> None:
        page = _Page(
            [
                {
                    "ok": False,
                    "matchCount": 1,
                    "reason": "控件中心被其他元素遮挡",
                    "blocker": "h2.jjb-banner__title",
                }
            ]
        )

        with self.assertRaises(AssertionError) as caught:
            _cart(page)._click_visible_control("button", description="加购")

        message = str(caught.exception)
        self.assertIn("遮挡", message)
        self.assertIn("h2.jjb-banner__title", message)
        self.assertEqual(page.evaluate_calls, 1, "确定性失败不应重试")

    def test_disabled_control_fails_immediately(self) -> None:
        page = _Page([{"ok": False, "matchCount": 1, "reason": "控件处于禁用状态"}])

        with self.assertRaises(AssertionError) as caught:
            _cart(page)._click_visible_control("button", description="加购")

        self.assertIn("禁用", str(caught.exception))
        self.assertEqual(page.evaluate_calls, 1)

    def test_multiple_matches_fails_immediately(self) -> None:
        """定位到多个控件说明选择器不够精确，不能任选一个点击。"""
        page = _Page([{"ok": False, "matchCount": 3, "reason": "命中 3 个控件"}])

        with self.assertRaises(AssertionError) as caught:
            _cart(page)._click_visible_control("button", description="加购")

        self.assertIn("3", str(caught.exception))
        self.assertEqual(page.mouse.clicks, [])


class NavigationTolerationTests(unittest.TestCase):
    """点击触发导航会销毁执行上下文；只有确认 URL 变化才可放过异常。"""

    def test_navigation_error_is_tolerated_when_url_changed(self) -> None:
        page = _Page([PlaywrightError("Execution context was destroyed")])
        page._navigated_to = "https://jujubit.ai/cart"

        _cart(page)._click_visible_control(
            "button", description="点击 Checkout", allow_navigation=True
        )

        self.assertEqual(page.wait_for_function_calls, 1)

    def test_error_is_reraised_when_url_did_not_change(self) -> None:
        """URL 没变说明不是导航，异常必须原样抛出，不能被误吞成通过。"""
        page = _Page([PlaywrightError("Execution context was destroyed")])

        with self.assertRaises(PlaywrightError):
            _cart(page)._click_visible_control(
                "button", description="点击 Checkout", allow_navigation=True
            )

    def test_error_is_reraised_when_navigation_not_allowed(self) -> None:
        page = _Page([PlaywrightError("boom")])
        page._navigated_to = "https://jujubit.ai/cart"

        with self.assertRaises(PlaywrightError):
            _cart(page)._click_visible_control("button", description="加购")

        self.assertEqual(
            page.wait_for_function_calls, 0, "未允许导航时不应做 URL 探测"
        )


class InjectedScriptContractTests(unittest.TestCase):
    def test_script_reuses_shared_visibility_helper(self) -> None:
        import inspect

        source = inspect.getsource(CartPage._click_visible_control)

        self.assertIn("__IS_RENDERED__", source)
        self.assertIn("IS_RENDERED_JS", source)
        # 不能自己再写一份可见性判定。
        self.assertNotIn("style.visibility === 'hidden'", source)

    def test_script_distinguishes_rendered_from_in_viewport(self) -> None:
        """首屏之外的控件必须先滚动再判遮挡，否则正常控件会被误报为 0 个。"""
        import inspect

        source = inspect.getsource(CartPage._click_visible_control)

        self.assertIn("isInViewport", source)
        self.assertIn("scrollIntoView", source)


if __name__ == "__main__":
    unittest.main()
