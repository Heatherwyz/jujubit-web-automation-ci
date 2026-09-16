"""Job Summary 渲染的离线单测。

Job Summary 是唯一能在浏览器里直接读的完整结论：GitHub 对仓库内的 .html 强制
``text/plain`` + ``nosniff``，点开只有源码；私有仓库又不能用 Pages。所以这份
Markdown 的正确性直接决定了"能不能看懂这一轮结果"。

口径必须与终端和飞书卡片一致：业务失败优先于未完成，有效覆盖而非通过率。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.write_job_summary import (
    build_summary,
    resolve_results_path,
)

RATE_LIMIT_DETAIL = "站点访问频控（HTTP 429）：jujubit.ai/cart.js 未完成。"


def _summary(
    *,
    total: int,
    passed: int,
    failed: int = 0,
    rate_limited: int = 0,
    ordinary_skipped: int = 0,
    failed_cases=(),
    unfinished_cases=(),
    modules=(),
) -> dict:
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": 0,
        "skipped": rate_limited + ordinary_skipped,
        "rate_limited": rate_limited,
        "rate_limited_skipped": rate_limited,
        "rate_limited_failures": 0,
        "ordinary_skipped": ordinary_skipped,
        "duration_seconds": 930,
        "modules": list(modules),
        "failed_cases": list(failed_cases),
        "unfinished_cases": list(unfinished_cases),
    }


class VerdictTests(unittest.TestCase):
    def test_all_passed(self) -> None:
        markdown = build_summary(_summary(total=30, passed=30))

        self.assertIn("✅ 全部通过", markdown)
        self.assertIn("**100%**（30/30）", markdown)

    def test_business_failure_outranks_unfinished(self) -> None:
        markdown = build_summary(
            _summary(total=30, passed=12, failed=1, rate_limited=17)
        )

        self.assertIn("❌ 发现业务失败：1/30 条", markdown)
        # 即使判为失败，也要如实反映只有 13/30 得出结论。
        self.assertIn("（13/30）", markdown)

    def test_rate_limited_run_is_orange_not_pass(self) -> None:
        markdown = build_summary(_summary(total=30, passed=13, rate_limited=17))

        self.assertIn("🟠 受站点频控影响：17 条未完成", markdown)
        self.assertIn("**43%**", markdown)
        self.assertNotIn("全部通过", markdown)

    def test_ordinary_skip_is_blue(self) -> None:
        markdown = build_summary(_summary(total=30, passed=28, ordinary_skipped=2))

        self.assertIn("🔵 执行完成，2 条未完成", markdown)

    def test_zero_results_is_flagged(self) -> None:
        markdown = build_summary(_summary(total=0, passed=0))

        self.assertIn("⚠️ 未取得测试结果", markdown)


class TableRenderingTests(unittest.TestCase):
    def test_failed_cases_table_lists_name_and_error(self) -> None:
        markdown = build_summary(
            _summary(
                total=21,
                passed=20,
                failed=1,
                failed_cases=[
                    {
                        "name": "test_cart_tc05_header_opens_full_cart[pc]",
                        "module": "购物车",
                        "detail": "AssertionError: Gallery 加购接口失败：HTTP 503",
                    }
                ],
            )
        )

        self.assertIn("### ❌ 业务失败", markdown)
        self.assertIn("test_cart_tc05_header_opens_full_cart[pc]", markdown)
        self.assertIn("HTTP 503", markdown)

    def test_unfinished_table_includes_actionable_hint(self) -> None:
        """未完成必须说明该怎么处置，否则读者只知道"没跑"。"""
        markdown = build_summary(
            _summary(
                total=2,
                passed=1,
                rate_limited=1,
                unfinished_cases=[
                    {
                        "name": "test_add[pc]",
                        "module": "购物车",
                        "detail": RATE_LIMIT_DETAIL,
                    }
                ],
            )
        )

        self.assertIn("### ⏭ 未完成", markdown)
        self.assertIn("站点频控，等冷却后重跑", markdown)

    def test_known_issue_hint_points_at_recovery(self) -> None:
        markdown = build_summary(
            _summary(
                total=2,
                passed=1,
                ordinary_skipped=1,
                unfinished_cases=[
                    {
                        "name": "test_hero_lcp_media_is_eager[h5]",
                        "module": "首页",
                        "detail": "已知问题：H5 端 Hero 图片仍是 loading=lazy",
                    }
                ],
            )
        )

        self.assertIn("已登记的已知问题", markdown)

    def test_pipe_in_detail_does_not_break_table(self) -> None:
        """错误正文里的竖线必须转义，否则 Markdown 表格会错列。"""
        markdown = build_summary(
            _summary(
                total=1,
                passed=0,
                failed=1,
                failed_cases=[
                    {
                        "name": "test_x",
                        "module": "首页",
                        "detail": "expected a|b got c|d",
                    }
                ],
            )
        )

        self.assertIn("a\\|b", markdown)

    def test_module_table_is_rendered(self) -> None:
        markdown = build_summary(
            _summary(
                total=30,
                passed=29,
                failed=1,
                modules=[
                    {
                        "name": "首页",
                        "total": 30,
                        "passed": 29,
                        "failed": 1,
                        "errors": 0,
                        "skipped": 0,
                        "rate_limited": 0,
                        "rate_limited_skipped": 0,
                        "rate_limited_failures": 0,
                        "ordinary_skipped": 0,
                    }
                ],
            )
        )

        self.assertIn("### 模块结果", markdown)
        self.assertIn("| 首页 | 29 | 1 | 0 |", markdown)

    def test_empty_sections_are_omitted(self) -> None:
        markdown = build_summary(_summary(total=5, passed=5))

        self.assertNotIn("### ❌ 业务失败", markdown)
        self.assertNotIn("### ⏭ 未完成", markdown)


class ReportLinkTests(unittest.TestCase):
    def test_download_wording_makes_non_rendering_explicit(self) -> None:
        """必须说明这个链接是下载：GitHub 不渲染仓库内 HTML。"""
        markdown = build_summary(
            _summary(total=1, passed=1),
            report_url="https://raw.githubusercontent.com/o/r/test-reports/a.html",
            index_url="https://raw.githubusercontent.com/o/r/test-reports/index.html",
        )

        self.assertIn("下载本次 HTML 报告", markdown)
        self.assertIn("需下载后本地打开", markdown)
        self.assertIn("历史报告索引", markdown)

    def test_link_section_omitted_when_publish_failed(self) -> None:
        markdown = build_summary(_summary(total=1, passed=1))

        self.assertNotIn("### 完整报告", markdown)

    def test_coverage_caveat_is_always_present(self) -> None:
        markdown = build_summary(_summary(total=1, passed=1))

        self.assertIn("有效覆盖", markdown)


class ResultsPathTests(unittest.TestCase):
    """结果文件路径必须限定在仓库内，拒绝 .. 穿越。"""

    def test_relative_path_inside_repo_is_accepted(self) -> None:
        resolved = resolve_results_path("artifacts/runs/x/results.xml")

        self.assertTrue(str(resolved).endswith("artifacts/runs/x/results.xml"))

    def test_parent_traversal_is_rejected(self) -> None:
        with self.assertRaisesRegex(SystemExit, "仓库目录内"):
            resolve_results_path("../../etc/passwd")

    def test_absolute_path_outside_repo_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "results.xml"
            target.write_text("<testsuite/>", encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "仓库目录内"):
                resolve_results_path(str(target))


if __name__ == "__main__":
    unittest.main()
