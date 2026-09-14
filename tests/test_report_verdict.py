"""报告结论口径：失败与未完成必须是两个口径，不能互相掩盖。

历史问题：终端汇总和 HTML 首屏都只看 failed，skip 完全不参与判定，于是
“13 条通过 + 17 条因 429 未完成”会显示成执行通过、通过率 100%。未完成的
用例没有验证任何业务行为，既不算通过也不算失败，必须单独显性化。
"""

from __future__ import annotations

import re
import unittest

from python_playwright.tests.conftest import pytest_html_results_summary

RATE_LIMIT_DETAIL = "站点访问频控（HTTP 429）：jujubit.ai/cart.js 未完成。"


class _Config:
    def __init__(self, results, *, selected=None, deselected=0):
        self._jujubit_results = dict(enumerate(results))
        self._jujubit_suite_name = "每日购物车分层回归"
        self._jujubit_collection_counts = {
            "selected": selected if selected is not None else len(results),
            "deselected": deselected,
        }


class _Session:
    def __init__(self, config):
        self.config = config


def _case(outcome: str, title: str, detail: str = "") -> dict:
    return {"outcome": outcome, "platform": "pc", "title": title, "detail": detail}


def _render(results) -> str:
    prefix: list[str] = []
    pytest_html_results_summary(prefix, None, None, session=_Session(_Config(results)))
    return "".join(prefix)


def _verdict(html: str) -> str:
    match = re.search(r"<strong>(执行[^<]*)</strong>", html)
    return match.group(1) if match else ""


def _coverage(html: str) -> str:
    match = re.search(r"<strong>有效覆盖：</strong>([^<]*)", html)
    return match.group(1) if match else ""


class ReportVerdictTests(unittest.TestCase):
    def test_all_passed_reports_plain_pass_and_full_coverage(self) -> None:
        html = _render([_case("passed", f"用例{index}") for index in range(30)])

        self.assertEqual(_verdict(html), "执行通过")
        self.assertIn("100%", _coverage(html))
        self.assertIn("30/30", _coverage(html))

    def test_rate_limited_run_is_not_reported_as_passed(self) -> None:
        """13 通过 + 17 因 429 未完成不能显示执行通过。"""
        results = [_case("passed", f"用例{index}") for index in range(13)]
        results += [
            _case("skipped", f"用例{index}", RATE_LIMIT_DETAIL) for index in range(17)
        ]

        html = _render(results)
        verdict = _verdict(html)

        self.assertNotEqual(verdict, "执行通过")
        self.assertIn("17/30", verdict)
        self.assertIn("未完成", verdict)
        coverage = _coverage(html)
        # 有效覆盖必须是 43%，而不是被读成 100% 通过率。
        self.assertIn("43%", coverage)
        self.assertNotIn("100%", coverage)
        self.assertIn("因 HTTP 429 未完成 17 条", coverage)

    def test_business_failure_outranks_incomplete_cases(self) -> None:
        """存在业务失败时结论必须是失败，未完成数不能把它盖过去。"""
        results = [_case("passed", f"用例{index}") for index in range(12)]
        results += [_case("failed", "购物车角标未更新")]
        results += [
            _case("skipped", f"用例{index}", RATE_LIMIT_DETAIL) for index in range(17)
        ]

        html = _render(results)
        verdict = _verdict(html)

        self.assertIn("执行失败", verdict)
        self.assertIn("1/30", verdict)
        # 即使判定为失败，也要如实给出只有 13/30 得出业务结论。
        self.assertIn("43%", _coverage(html))

    def test_ordinary_skip_also_lowers_effective_coverage(self) -> None:
        """非 429 的普通跳过同样没有验证业务行为，覆盖率必须扣减。"""
        results = [_case("passed", f"用例{index}") for index in range(28)]
        results += [_case("skipped", "当前页面未配置视频", "当前页面未配置视频")]
        results += [_case("skipped", "当前页面未配置 FAQ", "当前页面未配置 FAQ")]

        html = _render(results)

        self.assertIn("2/30", _verdict(html))
        coverage = _coverage(html)
        self.assertIn("93%", coverage)
        self.assertIn("因 HTTP 429 未完成 0 条", coverage)

    def test_empty_results_render_nothing(self) -> None:
        """离线单测不经过 page fixture，不应被伪装成一次线上回归结果。"""
        prefix: list[str] = []
        pytest_html_results_summary(
            prefix, None, None, session=_Session(_Config([]))
        )

        self.assertEqual(prefix, [])


if __name__ == "__main__":
    unittest.main()
