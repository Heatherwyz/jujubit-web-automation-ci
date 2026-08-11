"""购物车请求节流、429 退避和熔断的离线回归测试。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from python_playwright.pages.cart_page import CartPage
from python_playwright.pages.home_page import SiteRateLimitError


class _Response:
    """提供购物车请求逻辑所需的最小响应接口。"""

    def __init__(self, status: int, *, headers=None, payload=None, url="https://jujubit.ai/cart.js"):
        self.status = status
        self.headers = headers or {}
        self.url = url
        self.ok = 200 <= status < 300
        self._payload = payload or {"item_count": 0}

    def json(self):
        return self._payload


class _RequestClient:
    """按顺序返回响应，并记录 GET/POST 是否被重复发送。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url: str, **kwargs):
        self.calls.append(("get", url, kwargs))
        return self.responses.pop(0)

    def post(self, url: str, **kwargs):
        self.calls.append(("post", url, kwargs))
        return self.responses.pop(0)


class _Page:
    def __init__(self, responses):
        self.request = _RequestClient(responses)


class _Pacer:
    def __init__(self):
        self.calls = 0

    def wait(self):
        self.calls += 1


class _Config:
    def __init__(self, retries: int):
        self.retries = retries
        self._jujubit_cart_pacer = _Pacer()
        self._jujubit_cart_rate_limited = ""
        self._jujubit_site_rate_limited = ""

    def getoption(self, name: str):
        if name == "--pw-429-retries":
            return self.retries
        raise AssertionError(f"未预期读取配置项：{name}")


class _Home:
    @staticmethod
    def _retry_delay(_attempt: int, retry_after: str | None = None) -> float:
        return float(retry_after or 15)


class CartRateLimitTests(unittest.TestCase):
    """保证只对安全请求退避，并在持续 429 后停止后续访问。"""

    def _cart(self, responses, *, retries: int = 1):
        cart = object.__new__(CartPage)
        cart.page = _Page(responses)
        cart.base_url = "https://jujubit.ai"
        cart.config = _Config(retries)
        cart.home = _Home()
        cart._rate_limited_urls = []
        return cart

    def test_cart_get_honors_retry_after_then_returns_success(self) -> None:
        cart = self._cart(
            [
                _Response(429, headers={"retry-after": "7"}),
                _Response(200, payload={"item_count": 1}),
            ]
        )

        with patch("python_playwright.pages.cart_page.time.sleep") as sleep:
            result = cart.cart_json()

        self.assertEqual(result["item_count"], 1)
        self.assertEqual(len(cart.page.request.calls), 2)
        self.assertEqual(cart.config._jujubit_cart_pacer.calls, 2)
        sleep.assert_called_once_with(7.0)

    def test_clear_cart_can_retry_because_repeating_clear_is_safe(self) -> None:
        cart = self._cart([_Response(429), _Response(200)])

        with patch("python_playwright.pages.cart_page.time.sleep"):
            cart.clear_cart()

        self.assertEqual(
            [method for method, _url, _kwargs in cart.page.request.calls],
            ["post", "post"],
        )

    def test_empty_cart_check_does_not_send_unnecessary_clear(self) -> None:
        """新 context 本来就是空车时，只读一次 cart.js。"""
        cart = self._cart([_Response(200, payload={"item_count": 0})])

        cart.ensure_empty_cart()

        self.assertEqual(
            [method for method, _url, _kwargs in cart.page.request.calls],
            ["get"],
        )

    def test_nonempty_cart_is_cleared_after_reading_current_state(self) -> None:
        """只有服务端确认存在商品时才调用 cart/clear.js。"""
        cart = self._cart(
            [_Response(200, payload={"item_count": 2}), _Response(200)]
        )

        cart.ensure_empty_cart()

        self.assertEqual(
            [method for method, _url, _kwargs in cart.page.request.calls],
            ["get", "post"],
        )

    def test_exhausted_429_opens_circuit_and_blocks_later_requests(self) -> None:
        cart = self._cart([_Response(429), _Response(429), _Response(200)])

        with patch("python_playwright.pages.cart_page.time.sleep"):
            with self.assertRaises(SiteRateLimitError):
                cart.cart_json()

        self.assertIn("HTTP 429", cart.config._jujubit_cart_rate_limited)
        self.assertEqual(
            cart.config._jujubit_cart_rate_limited,
            cart.config._jujubit_site_rate_limited,
        )
        first_attempt_count = len(cart.page.request.calls)

        # teardown 的 ignore_errors 仍可调用，但熔断会在真正发请求前直接返回。
        cart.clear_cart(ignore_errors=True)
        self.assertEqual(len(cart.page.request.calls), first_attempt_count)

    def test_listener_429_blocks_the_next_cart_request_before_sending_it(self) -> None:
        """异步 Creator/API 429 必须在下一次关键操作前熔断。"""
        cart = self._cart([_Response(200)])
        cart._record_rate_limit(
            _Response(429, url="https://jujubit.ai/products/customize-your-own")
        )

        with self.assertRaises(SiteRateLimitError):
            cart.cart_json()

        self.assertEqual(cart.page.request.calls, [])
        self.assertIn("HTTP 429", cart.config._jujubit_cart_rate_limited)

    def test_listener_ignores_home_document_429_handled_by_home_page_retry(self) -> None:
        """首页主文档由 HomePage 自己退避，不能提前把购物车熔断。"""
        cart = self._cart([_Response(200)])
        cart._record_rate_limit(_Response(429, url="https://jujubit.ai/"))

        self.assertEqual(cart._rate_limited_urls, [])

    def test_retry_helper_rejects_non_idempotent_write_operations(self) -> None:
        """未来维护时也不能把加购、改数量等写接口接入自动重试。"""
        cart = self._cart([])

        with self.assertRaisesRegex(AssertionError, "禁止重放"):
            cart._request_with_rate_limit_retry(
                "post",
                "https://jujubit.ai/cart/add.js",
                operation="加购时",
            )


if __name__ == "__main__":
    unittest.main()
