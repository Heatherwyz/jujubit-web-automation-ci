"""飞书测试摘要脚本的本地单元测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.send_lark_test_report import (
    _format_started_at,
    _suite_execution_lines,
    card_template,
    module_for_case,
    read_results,
)
from xml.etree import ElementTree


class LarkReportTests(unittest.TestCase):
    """验证报告解析、模块归类和卡片关键信息。"""

    def test_module_classification_prefers_test_owner(self) -> None:
        home_cart_entry = ElementTree.fromstring(
            '<testcase classname="python_playwright.tests.test_home" '
            'name="test_cart_entry_exists[pc]" />'
        )
        home_cart_file = ElementTree.fromstring(
            '<testcase file="python_playwright/tests/test_home_cart_entry.py" '
            'name="test_cart_entry_exists[pc]" />'
        )
        cart_file = ElementTree.fromstring(
            '<testcase file="python_playwright/tests/test_cart.py" '
            'name="test_add_item[pc]" />'
        )
        cart_name = ElementTree.fromstring(
            '<testcase classname="tests.test_checkout" '
            'name="test_shopping_cart_quantity[h5]" />'
        )

        self.assertEqual(module_for_case(home_cart_entry), "首页")
        self.assertEqual(module_for_case(home_cart_file), "首页")
        self.assertEqual(module_for_case(cart_file), "购物车")
        self.assertEqual(module_for_case(cart_name), "购物车")

    def test_read_results_includes_duration_and_module_totals(self) -> None:
        xml = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="4" time="91.4"
             timestamp="2026-08-06T09:15:20.123456+08:00">
    <testcase classname="python_playwright.tests.test_home" name="test_load[pc]" time="1.2" />
    <testcase classname="python_playwright.tests.test_home" name="test_optional[h5]" time="0.7">
      <skipped message="条件不满足" />
    </testcase>
    <testcase classname="python_playwright.tests.test_cart" name="test_add[pc]" time="2.0">
      <failure message="商品未加入购物车" />
    </testcase>
    <testcase file="python_playwright/tests/test_cart.py" name="test_open[h5]" time="3.0">
      <error message="首页请求失败：HTTP 429，访问频控" />
    </testcase>
  </testsuite>
</testsuites>
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            results_path = Path(temp_dir) / "results.xml"
            results_path.write_text(xml, encoding="utf-8")
            summary = read_results(str(results_path))

        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["passed"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["rate_limited"], 1)
        self.assertEqual(summary["rate_limited_skipped"], 0)
        self.assertEqual(summary["ordinary_skipped"], 1)
        self.assertEqual(summary["duration_seconds"], 91.4)
        self.assertEqual(summary["started_at"], "2026-08-06T09:15:20.123456+08:00")
        self.assertEqual([module["name"] for module in summary["modules"]], ["首页", "购物车"])
        self.assertEqual(summary["modules"][0]["total"], 2)
        self.assertEqual(summary["modules"][1]["total"], 2)
        self.assertEqual(summary["modules"][1]["rate_limited"], 1)

    def test_rate_limited_skips_are_counted_once_and_rendered_as_unfinished(self) -> None:
        """429 是跳过原因，不应在卡片中与跳过项重复累计。"""
        xml = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="4" time="12">
  <testcase classname="python_playwright.tests.test_home" name="test_ok[pc]" time="1" />
  <testcase classname="python_playwright.tests.test_home" name="test_requirement[h5]" time="2">
    <failure message="需求不符合" />
  </testcase>
  <testcase classname="python_playwright.tests.test_home" name="test_link_scan[pc]" time="3">
    <skipped message="HTTP 429 Too Many Requests" />
  </testcase>
  <testcase classname="python_playwright.tests.test_home" name="test_optional[h5]" time="4">
    <skipped message="当前环境未配置" />
  </testcase>
</testsuite>
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            results_path = Path(temp_dir) / "results.xml"
            results_path.write_text(xml, encoding="utf-8")
            summary = read_results(str(results_path))

        self.assertEqual(summary["rate_limited"], 1)
        self.assertEqual(summary["rate_limited_skipped"], 1)
        self.assertEqual(summary["ordinary_skipped"], 1)
        card_text = json.dumps(card_template(summary), ensure_ascii=False)
        self.assertIn("429 未完成 / 其他跳过", card_text)
        self.assertIn("1 / 1", card_text)
        self.assertIn("业务失败", card_text)

    def test_legacy_summary_does_not_double_count_rate_limited_skip(self) -> None:
        """兼容旧版运行结果时，429 跳过不能再被展示成其他跳过。"""
        legacy_summary = {
            "total": 62,
            "passed": 44,
            "failed": 16,
            "errors": 0,
            "skipped": 2,
            "rate_limited": 2,
            "rate_limited_failures": 0,
            "duration_seconds": 574,
            "started_at": "",
            "modules": [],
        }

        card_text = json.dumps(card_template(legacy_summary), ensure_ascii=False)
        self.assertIn("2 / 0", card_text)

    def test_card_contains_execution_and_module_details(self) -> None:
        summary = {
            "total": 5,
            "passed": 4,
            "failed": 1,
            "errors": 0,
            "skipped": 0,
            "rate_limited": 0,
            "rate_limited_failures": 0,
            "duration_seconds": 82,
            "started_at": "2026-08-06T09:15:20+08:00",
            "modules": [
                {
                    "name": "首页",
                    "total": 3,
                    "passed": 3,
                    "failed": 0,
                    "errors": 0,
                    "skipped": 0,
                    "rate_limited": 0,
                    "rate_limited_failures": 0,
                    "duration_seconds": 32,
                },
                {
                    "name": "购物车",
                    "total": 2,
                    "passed": 1,
                    "failed": 1,
                    "errors": 0,
                    "skipped": 0,
                    "rate_limited": 0,
                    "rate_limited_failures": 0,
                    "duration_seconds": 50,
                },
            ],
        }
        card = card_template(
            summary,
            "https://github.example/run/1",
            "https://github.example/artifact/1",
            "1",
            "20260806-091520",
            "main",
            "tester",
            "1234567890abcdef",
            "",
        )
        card_text = json.dumps(card, ensure_ascii=False)

        self.assertIn("JuJuBit 自动化测试", card_text)
        self.assertIn("80.0%（4/5）", card_text)
        self.assertIn("1分22秒", card_text)
        self.assertIn("main", card_text)
        self.assertIn("tester", card_text)
        self.assertIn("1234567", card_text)
        self.assertIn("首页", card_text)
        self.assertIn("购物车", card_text)
        self.assertIn("https://github.example/run/1", card_text)
        self.assertIn("https://github.example/artifact/1", card_text)

    def test_card_contains_suite_scope_and_actual_count(self) -> None:
        """计划数与 JUnit 实际数不一致时不能显示绿色全部通过。"""
        summary = {
            "total": 20,
            "passed": 20,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "rate_limited": 0,
            "ordinary_skipped": 0,
            "duration_seconds": 12,
            "modules": [],
        }
        card = card_template(
            summary,
            suite="daily",
            planned_cases="21",
            actual_cases="20",
        )
        card_text = json.dumps(card, ensure_ascii=False)
        self.assertIn("每日分层：PC 15 条 + H5 关键 6 条", card_text)
        # 实际数以 XML summary.total 为准，不能被错误的工作流兜底值覆盖。
        self.assertIn("计划 / 实际执行", card_text)
        self.assertIn("21 条 / 20 条", card_text)
        self.assertEqual(card["card"]["header"]["template"], "orange")
        self.assertIn("计划与实际用例数不一致", card["card"]["header"]["title"]["content"])
        self.assertIn("计划与实际不一致：计划执行 21 条，JUnit 实际生成 20 条", card_text)

    def test_matching_planned_count_can_be_all_green(self) -> None:
        """计划数与 JUnit 实际数相同时，全通过结果仍显示绿色。"""
        summary = {
            "total": 21,
            "passed": 21,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "rate_limited": 0,
            "ordinary_skipped": 0,
            "duration_seconds": 12,
            "modules": [],
        }

        card = card_template(summary, suite="daily", planned_cases="21")

        self.assertEqual(card["card"]["header"]["template"], "green")
        self.assertIn("全部通过", card["card"]["header"]["title"]["content"])

    def test_zero_results_keeps_existing_empty_result_status(self) -> None:
        """即使提供计划数，total=0 仍使用原有的未取得结果逻辑。"""
        summary = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "rate_limited": 0,
            "ordinary_skipped": 0,
            "duration_seconds": 0,
            "modules": [],
        }

        card = card_template(summary, planned_cases="21")

        self.assertEqual(card["card"]["header"]["template"], "orange")
        self.assertIn("未取得测试结果", card["card"]["header"]["title"]["content"])
        self.assertNotIn("计划与实际不一致", json.dumps(card, ensure_ascii=False))

    def test_started_at_keeps_cst_timezone_suffix(self) -> None:
        """GitHub 传入的 CST 不应被 ISO 时间分隔符替换逻辑破坏。"""
        self.assertEqual(
            _format_started_at("2026-08-06 17:02:41 CST"),
            "2026-08-06 17:02:41 CST",
        )
        self.assertEqual(
            _format_started_at("2026-08-06T17:02:41.123456+08:00"),
            "2026-08-06 17:02:41+08:00",
        )

    def test_process_error_is_not_hidden_by_empty_results(self) -> None:
        """pytest 未产出结果且进程异常时，卡片必须显示红色进程错误。"""
        summary = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "rate_limited": 0,
            "rate_limited_failures": 0,
            "duration_seconds": 0,
            "started_at": "",
            "modules": [],
        }
        card = card_template(summary, exit_code="2")

        self.assertEqual(card["card"]["header"]["template"], "red")
        self.assertIn("测试进程异常", card["card"]["header"]["title"]["content"])


if __name__ == "__main__":
    unittest.main()
