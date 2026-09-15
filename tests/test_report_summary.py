"""报告首屏摘要模块的离线单测。

从 conftest 抽出来后，判定口径（compute_verdict）和渲染（build_summary_html）都
能直接调用，不必伪造 session。这里覆盖的核心不变量是：失败与未完成是两个口径，
未完成的用例既不算通过也不算失败。

tests/test_report_verdict.py 覆盖的是 conftest hook 那一层的接线，这里覆盖纯逻辑。
"""

from __future__ import annotations

import unittest

from python_playwright.report_summary import (
    BANNER_FAILED,
    BANNER_PASSED,
    BANNER_UNFINISHED,
    build_summary_html,
    compute_verdict,
)

RATE_LIMIT_DETAIL = "站点访问频控（HTTP 429）：jujubit.ai/cart.js 未完成。"


def _case(outcome: str, title: str = "用例", detail: str = "", **extra) -> dict:
    item = {"outcome": outcome, "platform": "pc", "title": title, "detail": detail}
    item.update(extra)
    return item


def _results(passed=0, failed=0, rate_limited=0, ordinary_skipped=0) -> list[dict]:
    items = [_case("passed", f"通过{i}") for i in range(passed)]
    items += [_case("failed", f"失败{i}", "断言失败") for i in range(failed)]
    items += [
        _case("skipped", f"频控{i}", RATE_LIMIT_DETAIL) for i in range(rate_limited)
    ]
    items += [
        _case("skipped", f"跳过{i}", "当前页面未配置") for i in range(ordinary_skipped)
    ]
    return items


class VerdictTests(unittest.TestCase):
    def test_all_passed(self) -> None:
        verdict = compute_verdict(_results(passed=30))

        self.assertEqual(verdict.headline, "执行通过")
        self.assertEqual(verdict.banner_color, BANNER_PASSED)
        self.assertEqual(verdict.executed, 30)
        self.assertEqual(verdict.coverage, 100.0)

    def test_rate_limited_run_is_not_reported_as_passed(self) -> None:
        """13 通过 + 17 条未完成：旧口径会显示执行通过、通过率 100%。"""
        verdict = compute_verdict(_results(passed=13, rate_limited=17))

        self.assertNotEqual(verdict.headline, "执行通过")
        self.assertIn("17/30", verdict.headline)
        self.assertEqual(verdict.banner_color, BANNER_UNFINISHED)
        self.assertEqual(verdict.executed, 13)
        self.assertAlmostEqual(verdict.coverage, 43.3, delta=0.1)
        self.assertEqual(verdict.rate_limited, 17)

    def test_business_failure_outranks_unfinished(self) -> None:
        verdict = compute_verdict(_results(passed=12, failed=1, rate_limited=17))

        self.assertIn("执行失败", verdict.headline)
        self.assertIn("1/30", verdict.headline)
        self.assertEqual(verdict.banner_color, BANNER_FAILED)
        # 即使判为失败，也要如实反映只有 13/30 得出结论。
        self.assertEqual(verdict.executed, 13)

    def test_ordinary_skip_also_lowers_coverage(self) -> None:
        verdict = compute_verdict(_results(passed=28, ordinary_skipped=2))

        self.assertEqual(verdict.executed, 28)
        self.assertAlmostEqual(verdict.coverage, 93.3, delta=0.1)
        self.assertEqual(verdict.rate_limited, 0, "普通跳过不应计入 429")

    def test_xpassed_counts_as_failure(self) -> None:
        """意外通过说明预期标记已过时，需要人处理，不能算通过。"""
        verdict = compute_verdict([_case("xpassed", "意外通过的用例")])

        self.assertEqual(len(verdict.failed), 1)
        self.assertIn("执行失败", verdict.headline)

    def test_xfailed_counts_as_unfinished(self) -> None:
        verdict = compute_verdict([_case("xfailed", "预期失败的用例")])

        self.assertEqual(len(verdict.unfinished), 1)
        self.assertEqual(len(verdict.failed), 0)

    def test_empty_results_do_not_divide_by_zero(self) -> None:
        verdict = compute_verdict([])

        self.assertEqual(verdict.total, 0)
        self.assertEqual(verdict.coverage, 0.0)
        self.assertEqual(verdict.headline, "执行通过")

    def test_coverage_text_omits_unfinished_clause_when_none(self) -> None:
        text = compute_verdict(_results(passed=5)).coverage_text

        self.assertIn("5/5", text)
        self.assertNotIn("未完成", text)


class SummaryHtmlTests(unittest.TestCase):
    def test_empty_results_render_nothing(self) -> None:
        """离线单测不产生结果，不应被伪装成一次线上回归。"""
        self.assertEqual(build_summary_html([]), "")

    def test_three_tables_are_present(self) -> None:
        html = build_summary_html(_results(passed=2, failed=1, rate_limited=1))

        self.assertIn("通过用例（2）", html)
        self.assertIn("失败用例（1）", html)
        self.assertIn("未完成 / 跳过用例（1", html)

    def test_unfinished_table_is_omitted_when_none(self) -> None:
        html = build_summary_html(_results(passed=3))

        self.assertNotIn("未完成 / 跳过用例", html)

    def test_headline_and_coverage_appear_in_banner(self) -> None:
        html = build_summary_html(_results(passed=13, rate_limited=17))

        self.assertIn("执行完成但 17/30 条未完成", html)
        self.assertIn("有效覆盖", html)
        self.assertIn("43%（13/30 条得出业务结论", html)

    def test_suite_name_and_deselected_count_are_rendered(self) -> None:
        html = build_summary_html(
            _results(passed=1),
            suite_name="每日购物车分层回归",
            selected_count=31,
            deselected_count=5,
        )

        self.assertIn("每日购物车分层回归", html)
        self.assertIn("本次收集：</strong>31 条", html)
        self.assertIn("分层排除 5 条", html)

    def test_html_special_characters_are_escaped(self) -> None:
        """用例标题与错误详情来自站点内容，必须转义防止破坏报告结构。"""
        html = build_summary_html(
            [_case("failed", "<script>alert(1)</script>", "详情 & <b>粗体</b>")]
        )

        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp;", html)

    def test_screenshot_and_video_links_are_rendered(self) -> None:
        html = build_summary_html(
            [
                _case(
                    "failed",
                    "购物车角标",
                    "断言失败",
                    screenshot="screenshots/a.png",
                    video="videos/a.webm",
                )
            ]
        )

        self.assertIn("screenshots/a.png", html)
        self.assertIn("videos/a.webm", html)

    def test_missing_attachments_are_reported_explicitly(self) -> None:
        """缺附件要写明原因，避免让人以为忘了截图。"""
        html = build_summary_html(
            [_case("failed", "购物车角标", "断言失败", screenshot_error="页面已关闭")]
        )

        self.assertIn("截图未生成：页面已关闭", html)
        self.assertIn("视频未生成", html)

    def test_failure_location_includes_selector_and_viewport(self) -> None:
        html = build_summary_html(
            [
                _case(
                    "failed",
                    "购物车角标",
                    "断言失败",
                    page_url="https://jujubit.ai/cart",
                    page_title="Cart",
                    evidence={
                        "selector": ".ccd-qty-num",
                        "description": "数量输入框",
                        "viewport": "1440x900",
                    },
                )
            ]
        )

        self.assertIn(".ccd-qty-num", html)
        self.assertIn("数量输入框", html)
        self.assertIn("1440x900", html)
        self.assertIn("https://jujubit.ai/cart", html)

    def test_unknown_outcome_does_not_crash(self) -> None:
        html = build_summary_html([_case("weird_state", "未知状态用例")])

        self.assertIn("未知状态用例", html)


if __name__ == "__main__":
    unittest.main()
