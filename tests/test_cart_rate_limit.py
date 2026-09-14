"""购物车请求节流、429 退避和熔断的离线回归测试。"""

from __future__ import annotations

import time
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
    def __init__(self, retries: int, cooldown: float = 0.0):
        self.retries = retries
        self.cooldown = cooldown
        self._jujubit_cart_pacer = _Pacer()
        self._jujubit_cart_rate_limited = ""
        self._jujubit_site_rate_limited = ""
        self._jujubit_cart_rate_limited_at = None
        self._jujubit_site_rate_limited_at = None

    def getoption(self, name: str):
        if name == "--pw-429-retries":
            return self.retries
        if name == "--pw-429-cooldown":
            return self.cooldown
        raise AssertionError(f"未预期读取配置项：{name}")


class _Home:
    @staticmethod
    def _retry_delay(_attempt: int, retry_after: str | None = None) -> float:
        return float(retry_after or 15)


class CartRateLimitTests(unittest.TestCase):
    """保证只对安全请求退避，并在持续 429 后停止后续访问。"""

    def _cart(self, responses, *, retries: int = 1, cooldown: float = 0.0):
        cart = object.__new__(CartPage)
        cart.page = _Page(responses)
        cart.base_url = "https://jujubit.ai"
        cart.config = _Config(retries, cooldown)
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

    def test_listener_ignores_analytics_ingest_429_without_opening_cart_circuit(self) -> None:
        """分析埋点限流不能把实际购物车回归误标为未完成。"""
        cart = self._cart([_Response(200, payload={"item_count": 1})])
        cart._record_rate_limit(
            _Response(
                429,
                url=(
                    "https://jujubit.ai/apps/monitor/api/collect/batch/add/"
                    "?source=playwright"
                ),
            )
        )

        self.assertEqual(cart._rate_limited_urls, [])
        self.assertEqual(cart.cart_json()["item_count"], 1)
        self.assertEqual(len(cart.page.request.calls), 1)
        self.assertEqual(cart.config._jujubit_cart_rate_limited, "")

    def test_retry_helper_rejects_non_idempotent_write_operations(self) -> None:
        """未来维护时也不能把加购、改数量等写接口接入自动重试。"""
        cart = self._cart([])

        with self.assertRaisesRegex(AssertionError, "禁止重放"):
            cart._request_with_rate_limit_retry(
                "post",
                "https://jujubit.ai/cart/add.js",
                operation="加购时",
            )


class _Resp429:
    def __init__(self, url: str, status: int = 429):
        self.url = url
        self.status = status


class RateLimitScopeTests(unittest.TestCase):
    """只有业务请求的 429 才应熔断；静态资源被限流不影响购物车能否完成。

    此前把 CDN 图片、字体、主题 CSS 的 429 一并计入，于是一张图片超限就能让
    整条用例变成"未完成"，把真实的 UI/服务端不一致缺陷静默吞掉。
    """

    def _cart(self):
        cart = object.__new__(CartPage)
        cart.base_url = "https://jujubit.ai"
        cart._rate_limited_urls = []
        return cart

    def _records(self, url: str) -> bool:
        cart = self._cart()
        cart._record_rate_limit(_Resp429(url))
        return bool(cart._rate_limited_urls)

    def test_cart_apis_still_trip_the_circuit(self) -> None:
        """Shopify 购物车接口都以 .js 结尾，不能被静态资源规则误伤。"""
        for url in (
            "https://jujubit.ai/cart.js",
            "https://jujubit.ai/cart/add.js",
            "https://jujubit.ai/cart/change.js",
            "https://jujubit.ai/cart/clear.js",
        ):
            self.assertTrue(self._records(url), url)

    def test_business_documents_still_trip_the_circuit(self) -> None:
        for url in (
            "https://jujubit.ai/products/custom-figurine",
            "https://jujubit.ai/checkout",
            "https://jujubit.ai/apps/generate/api/create",
        ):
            self.assertTrue(self._records(url), url)

    def test_static_assets_do_not_trip_the_circuit(self) -> None:
        for url in (
            "https://jujubit.ai/cdn/shop/files/a.png",
            "https://jujubit.ai/assets/theme.css",
            "https://jujubit.ai/assets/cart-drawer.js",
            "https://jujubit.ai/assets/font.woff2",
            "https://cdn.jujubit.ai/img/hero.jpg",
            "https://jujubit.ai/files/banner.webp",
        ):
            self.assertFalse(self._records(url), url)

    def test_analytics_ingest_remains_exempt(self) -> None:
        self.assertFalse(
            self._records(
                "https://jujubit.ai/apps/monitor/api/collect/batch/add"
            )
        )

    def test_non_429_and_third_party_are_ignored(self) -> None:
        cart = self._cart()
        cart._record_rate_limit(_Resp429("https://jujubit.ai/cart/add.js", status=200))
        cart._record_rate_limit(_Resp429("https://example.com/cart/add.js"))

        self.assertEqual(cart._rate_limited_urls, [])


class CartCircuitCooldownTests(unittest.TestCase):
    """熔断冷却：一次瞬时 429 不能把整轮剩余用例全部标为未完成。"""

    def _cart(self, responses, *, retries: int = 0, cooldown: float = 120.0):
        cart = object.__new__(CartPage)
        cart.page = _Page(responses)
        cart.base_url = "https://jujubit.ai"
        cart.config = _Config(retries, cooldown)
        cart.home = _Home()
        cart._rate_limited_urls = []
        return cart

    def test_circuit_still_blocks_requests_inside_cooldown_window(self) -> None:
        """冷却未到时保持原有保护：不再向站点发新请求。"""
        cart = self._cart([_Response(429), _Response(200)], cooldown=120.0)

        with self.assertRaises(SiteRateLimitError):
            cart.cart_json()
        sent_before = len(cart.page.request.calls)

        # 距熔断仅过去 5 秒，远小于 120 秒冷却，必须继续熔断。
        cart.config._jujubit_cart_rate_limited_at = time.monotonic() - 5
        with self.assertRaises(SiteRateLimitError):
            cart.cart_json()
        self.assertEqual(len(cart.page.request.calls), sent_before)

    def test_circuit_half_opens_and_succeeds_after_cooldown_elapses(self) -> None:
        """冷却结束且站点已恢复时，后续用例必须能真正执行。"""
        cart = self._cart(
            [_Response(429), _Response(200, payload={"item_count": 3})],
            cooldown=120.0,
        )

        with self.assertRaises(SiteRateLimitError):
            cart.cart_json()
        self.assertNotEqual(cart.config._jujubit_cart_rate_limited, "")

        # 冷却已过：半开放行一次真实请求，站点恢复后熔断状态被清空。
        cart.config._jujubit_cart_rate_limited_at = time.monotonic() - 121
        self.assertEqual(cart.cart_json()["item_count"], 3)
        self.assertEqual(cart.config._jujubit_cart_rate_limited, "")
        self.assertEqual(cart.config._jujubit_site_rate_limited, "")
        self.assertEqual(cart._rate_limited_urls, [])

    def test_half_open_probe_that_is_still_limited_reopens_and_restarts_clock(self) -> None:
        """半开探测仍受限时必须重新熔断，并按新时刻重新计时。"""
        cart = self._cart([_Response(429), _Response(429)], cooldown=120.0)

        with self.assertRaises(SiteRateLimitError):
            cart.cart_json()
        opened_at = cart.config._jujubit_cart_rate_limited_at

        cart.config._jujubit_cart_rate_limited_at = time.monotonic() - 200
        with self.assertRaises(SiteRateLimitError):
            cart.cart_json()

        reopened_at = cart.config._jujubit_cart_rate_limited_at
        self.assertNotEqual(cart.config._jujubit_cart_rate_limited, "")
        self.assertIsNotNone(reopened_at)
        # 新的熔断时刻必须晚于被人为回拨的 -200 秒，否则冷却永远立即到期。
        self.assertGreater(reopened_at, time.monotonic() - 10)
        self.assertIsNotNone(opened_at)

    def test_cooldown_zero_preserves_permanent_circuit_behaviour(self) -> None:
        """显式关闭冷却时保留旧语义：熔断后本轮不再恢复。"""
        cart = self._cart([_Response(429), _Response(200)], cooldown=0.0)

        with self.assertRaises(SiteRateLimitError):
            cart.cart_json()
        sent_before = len(cart.page.request.calls)

        cart.config._jujubit_cart_rate_limited_at = time.monotonic() - 10_000
        with self.assertRaises(SiteRateLimitError):
            cart.cart_json()
        self.assertEqual(len(cart.page.request.calls), sent_before)


if __name__ == "__main__":
    unittest.main()
