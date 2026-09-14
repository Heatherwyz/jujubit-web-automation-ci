"""失败详情的频控判定：误判会让真实错误信息被整段丢弃。

conftest 的 _report_detail 在判定为频控时，会把 detail 替换成一句固定说明，
原始 traceback 完全丢失。所以这里的误判代价比飞书侧更高——报告里再也看不到
真实失败原因。原实现用 ``(?:http\\s*)?429``（http 前缀可选），裸的 429 三个
数字就命中，而 cart_page.py 有 2500+ 行，traceback 里出现 429 行号是常态。
"""

from __future__ import annotations

import unittest

from python_playwright.pages.home_page import RATE_LIMIT_DETAIL_PATTERN
from python_playwright.tests.conftest import _report_detail
from scripts.send_lark_test_report import RATE_LIMIT_PATTERN

RATE_LIMIT_NOTICE = "站点访问频控"


class _Report:
    def __init__(self, longrepr: str):
        self.longrepr = longrepr


class ReportDetailTests(unittest.TestCase):
    def test_ordinary_failures_keep_their_original_message(self) -> None:
        """普通业务失败必须原样保留，否则排查时没有任何线索。"""
        for message in (
            "E AssertionError: 购物车角标应为 2，实际 1",
            "E AssertionError: 元素宽 429px",
            "E assert 429 == 430",
            "home_page.py:429: in click_unobstructed",
            "E TimeoutError: Timeout 30000ms exceeded ... at cart_page.py:1429",
        ):
            detail = _report_detail(_Report(message))

            self.assertNotIn(RATE_LIMIT_NOTICE, detail, message)
            self.assertIn(message.strip()[:20], detail)

    def test_real_rate_limit_is_replaced_with_guidance(self) -> None:
        for message in (
            "E AssertionError: 站点访问频控（HTTP 429）：jujubit.ai/cart.js 未完成。",
            "Shopify Customer Account 登录服务返回 HTTP 429",
            "E playwright Error: rate limited by WAF",
        ):
            detail = _report_detail(_Report(message))

            self.assertIn(RATE_LIMIT_NOTICE, detail, message)

    def test_pytest_expanded_status_assertion_is_rate_limit(self) -> None:
        message = (
            "E assert 429 < 400  where 429 = "
            "<Response url='https://shopify.com/authentication/x'>.status"
        )

        self.assertIn(RATE_LIMIT_NOTICE, _report_detail(_Report(message)))

    def test_newlines_are_flattened_and_length_is_capped(self) -> None:
        detail = _report_detail(_Report("第一行\n第二行\n" + "x" * 3_000))

        self.assertNotIn("\n", detail)
        self.assertLessEqual(len(detail), 1_200)

    def test_empty_longrepr_falls_back_to_placeholder(self) -> None:
        self.assertEqual(_report_detail(_Report("")), "未提供错误详情")


class PatternConsistencyTests(unittest.TestCase):
    """conftest 与飞书脚本的频控口径必须一致。

    历史上飞书侧把正则修严了，conftest 侧的旧正则没同步，于是同一条失败在
    终端/HTML 报告里被当成频控、在飞书卡片里却算业务失败。
    """

    SAMPLES = (
        "E AssertionError: 站点访问频控（HTTP 429）",
        "Shopify Customer Account 登录服务返回 HTTP 429",
        "assert 429 < 400  where 429 = <Response url='https://x'>.status",
        "rate limited by WAF",
        "Too Many Requests",
        "Retry-After: 30",
        "频率限制触发",
        "E AssertionError: 元素宽 429px",
        "E assert 429 == 430",
        "home_page.py:429: in click_unobstructed",
        "E TimeoutError: Timeout 30000ms exceeded ... at cart_page.py:1429",
        "E AssertionError: 购物车角标应为 2，实际 1",
        "content-length 4290, got 429",
    )

    def test_both_patterns_agree_on_every_sample(self) -> None:
        for sample in self.SAMPLES:
            self.assertEqual(
                bool(RATE_LIMIT_DETAIL_PATTERN.search(sample)),
                bool(RATE_LIMIT_PATTERN.search(sample)),
                f"两处频控判定不一致：{sample}",
            )


if __name__ == "__main__":
    unittest.main()
