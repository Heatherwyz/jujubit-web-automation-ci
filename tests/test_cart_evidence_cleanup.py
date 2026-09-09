"""失败证据落盘与购物车清理顺序的离线回归测试。"""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from python_playwright.tests.conftest import _run_after_evidence_cleanups
from python_playwright.tests.test_cart import _isolated_cart


class _Config:
    def getoption(self, name: str):
        if name == "--base-url":
            return "https://jujubit.ai"
        raise KeyError(name)


class _Cart:
    def __init__(self, events, *, mutated: bool = True):
        self.events = events
        self.cart_was_mutated = mutated

    def ensure_empty_cart(self):
        self.events.append("前置清车")

    def _raise_if_rate_limited(self):
        return None

    def clear_cart(self, *, ignore_errors: bool = False):
        self.events.append("收尾清车")


class CartEvidenceCleanupTests(unittest.TestCase):
    def _request(self):
        return SimpleNamespace(config=_Config(), node=SimpleNamespace())

    def test_failed_case_does_not_clear_cart_before_evidence_teardown(self):
        events = []
        cart = _Cart(events)
        request = self._request()

        with patch(
            "python_playwright.tests.test_cart.CartPage", return_value=cart
        ):
            with self.assertRaisesRegex(AssertionError, "模拟业务失败"):
                with _isolated_cart(object(), request):
                    events.append("失败现场")
                    raise AssertionError("模拟业务失败")

        self.assertEqual(events, ["前置清车", "失败现场"])
        self.assertEqual(len(request.node._jujubit_after_evidence_cleanups), 1)

        events.append("截图和录像已保存")
        _run_after_evidence_cleanups(request.node)

        self.assertEqual(
            events,
            ["前置清车", "失败现场", "截图和录像已保存", "收尾清车"],
        )

    def test_successful_case_still_cleans_before_next_case(self):
        events = []
        cart = _Cart(events)
        request = self._request()

        with patch(
            "python_playwright.tests.test_cart.CartPage", return_value=cart
        ):
            with _isolated_cart(object(), request):
                events.append("用例通过")

        self.assertEqual(events, ["前置清车", "用例通过"])
        _run_after_evidence_cleanups(request.node)
        self.assertEqual(events, ["前置清车", "用例通过", "收尾清车"])
        self.assertFalse(
            hasattr(request.node, "_jujubit_after_evidence_cleanups"),
            "清理列表必须只消费一次，避免重复请求 cart/clear.js",
        )

        _run_after_evidence_cleanups(request.node)
        self.assertEqual(events.count("收尾清车"), 1)

    def test_read_only_or_unmutated_case_does_not_register_cleanup(self):
        for clear, mutated in ((False, True), (True, False)):
            with self.subTest(clear=clear, mutated=mutated):
                cart = _Cart([], mutated=mutated)
                request = self._request()
                with patch(
                    "python_playwright.tests.test_cart.CartPage", return_value=cart
                ):
                    with _isolated_cart(object(), request, clear=clear):
                        pass

                self.assertFalse(
                    hasattr(request.node, "_jujubit_after_evidence_cleanups")
                )


if __name__ == "__main__":
    unittest.main()
