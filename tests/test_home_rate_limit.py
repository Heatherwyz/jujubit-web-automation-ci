"""首页请求限速与 429 重试逻辑的离线单元测试。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from python_playwright.pages.home_page import HomePage, SiteRateLimitError
from python_playwright.pages.cart_page import SiteRateLimitError as CartRateLimitError


class _Response:
    """仅实现页面对象请求逻辑所需的最小响应接口。"""

    def __init__(self, status: int, body: str = "<main>页面内容</main>", headers=None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    def text(self) -> str:
        return self._body


class _RequestClient:
    """按预设顺序返回响应，并记录请求次数。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class _Page:
    """构造 HomePage 时用到的最小 Playwright Page 替身。"""

    def __init__(self, responses):
        self.request = _RequestClient(responses)

    def get_by_role(self, *args, **kwargs):
        return object()

    def locator(self, *args, **kwargs):
        return object()


class _Config:
    """提供测试所需的 pytest 配置选项和本次会话缓存。"""

    def __init__(self, retries: int):
        self.retries = retries
        self._jujubit_link_probe_cache = {}

    def getoption(self, name: str):
        if name == "--pw-429-retries":
            return self.retries
        raise AssertionError(f"未预期读取配置项：{name}")


class HomePageRateLimitTests(unittest.TestCase):
    """验证重试和缓存不会降低链接检查覆盖。"""

    def _home(self, responses, retries: int = 1) -> tuple[HomePage, _Page]:
        page = _Page(responses)
        home = HomePage(page, "https://jujubit.ai", _Config(retries))
        # 离线单元测试不验证计时器本身，只验证请求次数、退避和缓存语义。
        home._pace_site_request = lambda: None
        return home, page

    def test_request_retries_429_before_returning_success(self) -> None:
        """首个 429 应等待后重试，而不是立刻把整条用例标为跳过。"""
        home, page = self._home([_Response(429), _Response(200)], retries=1)

        with patch("python_playwright.pages.home_page.time.sleep") as sleep:
            response = home.get_with_rate_limit_retry("https://jujubit.ai/pages/gallery", timeout=8000)

        self.assertEqual(response.status, 200)
        self.assertEqual(len(page.request.calls), 2)
        sleep.assert_called_once_with(15.0)

    def test_link_probe_cache_reuses_same_url_for_pc_and_h5(self) -> None:
        """同一站内 URL 的第二次探测必须复用本次会话结果。"""
        home, page = self._home([_Response(200, "<main>Gallery</main>")])

        first = home.probe_internal_link("https://jujubit.ai/pages/gallery")
        second = home.probe_internal_link("https://jujubit.ai/pages/gallery")

        self.assertEqual(first, second)
        self.assertEqual(first["status"], 200)
        self.assertEqual(len(page.request.calls), 1)

    def test_rate_limited_probe_is_cached_without_repeating_requests(self) -> None:
        """429 耗尽重试后，同 URL 的另一端不会再次撞向站点频控。"""
        home, page = self._home([_Response(429)], retries=0)

        with self.assertRaises(SiteRateLimitError):
            home.probe_internal_link("https://jujubit.ai/pages/gallery")
        with self.assertRaises(SiteRateLimitError):
            home.probe_internal_link("https://jujubit.ai/pages/gallery")

        self.assertEqual(len(page.request.calls), 1)

    def test_transient_request_error_is_not_cached_across_platforms(self) -> None:
        """超时等瞬态异常必须允许另一端再次探测，不能被缓存为稳定失败。"""
        home, page = self._home([])
        calls = []

        def transient_then_success(url: str, *, timeout: int):
            calls.append((url, timeout))
            if len(calls) <= 2:
                from playwright.sync_api import Error as PlaywrightError

                raise PlaywrightError("temporary network timeout")
            return _Response(200, "<main>Gallery</main>")

        home.get_with_rate_limit_retry = transient_then_success
        first = home.probe_internal_link("https://jujubit.ai/pages/gallery")
        second = home.probe_internal_link("https://jujubit.ai/pages/gallery")

        self.assertIn("error", first)
        self.assertEqual(second["status"], 200)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(page.request.calls), 0)

    def test_retry_after_header_overrides_default_backoff(self) -> None:
        """站点提供 Retry-After 时，应优先遵循该等待时间。"""
        home, _ = self._home([], retries=1)

        self.assertEqual(home._retry_delay(0, "7"), 7.0)
        self.assertEqual(home._retry_delay(0, "999"), 90.0)
        self.assertEqual(home._retry_delay(1, "not-a-number"), 30.0)

    def test_cart_and_home_share_the_same_rate_limit_exception(self) -> None:
        """购物车首页入口遇到 429 时，测试层必须能按同一类型跳过。"""
        self.assertIs(CartRateLimitError, SiteRateLimitError)


if __name__ == "__main__":
    unittest.main()
