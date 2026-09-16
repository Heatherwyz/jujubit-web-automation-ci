"""飞书测试摘要脚本的本地单元测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.send_lark_test_report import (
    RATE_LIMIT_PATTERN,
    _business_failures,
    _failed_case_lines,
    _format_started_at,
    _suite_execution_lines,
    _validate_webhook_url,
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


class BusinessFailureCountTests(unittest.TestCase):
    """业务失败不能被 429 未完成数抹平——这两个是独立口径。"""

    def _summary(self, **kwargs):
        base = {"total": 30, "passed": 12, "failed": 0, "errors": 0, "skipped": 0}
        base.update(kwargs)
        return base

    def test_failure_is_not_cancelled_out_by_rate_limited_skips(self) -> None:
        """旧格式报告里 1 条真实失败 + 17 条 429 跳过，失败数必须仍是 1。

        回退逻辑曾直接用 rate_limited 相减（1 - 17 取 max 后为 0），
        真实业务失败被静默清零，卡片还会从红降级成橙。
        """
        summary = self._summary(failed=1, skipped=17, rate_limited=17)

        self.assertEqual(_business_failures(summary), 1)

    def test_rate_limited_failure_is_still_excluded(self) -> None:
        """以 failure 形式记录的 429 仍应从业务失败中剔除。"""
        summary = self._summary(failed=1, skipped=0, rate_limited=1)

        self.assertEqual(_business_failures(summary), 0)

    def test_explicit_split_fields_are_trusted(self) -> None:
        summary = self._summary(
            failed=3,
            skipped=17,
            rate_limited=18,
            rate_limited_skipped=17,
            rate_limited_failures=1,
        )

        self.assertEqual(_business_failures(summary), 2)

    def test_rate_limited_count_can_never_exceed_actual_failures(self) -> None:
        """频控计数异常偏大时也不能让业务失败变成负数或被抹平。"""
        summary = self._summary(failed=2, skipped=0, rate_limited_failures=99)

        self.assertEqual(_business_failures(summary), 0)

    def test_card_stays_red_when_failure_coexists_with_rate_limiting(self) -> None:
        """有业务失败时卡片必须是红色，不能被频控降级成橙色。"""
        summary = {
            "total": 30,
            "passed": 12,
            "failed": 1,
            "errors": 0,
            "skipped": 17,
            "rate_limited": 17,
            "rate_limited_skipped": 17,
            "rate_limited_failures": 0,
            "ordinary_skipped": 0,
            "duration": "5分0秒",
            "cases": [
                {
                    "module": "购物车",
                    "name": "test_badge",
                    "outcome": "failed",
                    "rate_limited": False,
                    "detail": "角标未更新",
                }
            ],
        }

        card = card_template(summary, exit_code="1")

        self.assertEqual(card["card"]["header"]["template"], "red")
        self.assertIn("业务失败", card["card"]["header"]["title"]["content"])

    def test_card_reports_executed_pass_rate_and_effective_coverage(self) -> None:
        """13 通过 + 17 条未完成：已执行通过率 100%，有效覆盖只有 43%。"""
        summary = {
            "total": 30,
            "passed": 13,
            "failed": 0,
            "errors": 0,
            "skipped": 17,
            "rate_limited": 17,
            "rate_limited_skipped": 17,
            "rate_limited_failures": 0,
            "ordinary_skipped": 0,
            "duration": "5分0秒",
            "cases": [],
        }

        card = card_template(summary, exit_code="0")
        contents = [
            field["text"]["content"]
            for element in card["card"]["elements"]
            for field in element.get("fields", [])
        ]
        rendered = "\n".join(contents)

        self.assertIn("已执行通过率", rendered)
        self.assertIn("100.0%（13/13）", rendered)
        self.assertIn("有效覆盖", rendered)
        self.assertIn("43%（13/30 条得出结论）", rendered)
        self.assertEqual(card["card"]["header"]["template"], "orange")


class RateLimitPatternTests(unittest.TestCase):
    """429 必须与 HTTP 语义相邻才算频控。

    此前用裸 \\b429\\b 匹配失败正文全文，traceback 里的 "line 429"、
    "assert 429 == 430"、"resolved after 429 ms" 都会把真实业务失败改判成
    "受站点频控影响"，卡片从红降级成橙。飞书卡片是 CI 唯一对外出口。
    """

    def test_real_rate_limit_messages_are_recognised(self) -> None:
        for message in (
            "Customer Account returned HTTP 429 Too Many Requests",
            "HTTP/1.1 429",
            "站点访问频控（HTTP 429）：jujubit.ai/cart.js 未完成。",
            "Shopify Customer Account 登录服务返回 HTTP 429",
            "响应 429",
            "rate limited by WAF",
            "rate-limit exceeded",
            "Too Many Requests",
            "Retry-After: 30",
            "频率限制触发",
        ):
            self.assertTrue(RATE_LIMIT_PATTERN.search(message), message)

    def test_pytest_expanded_status_assertion_is_recognised(self) -> None:
        """pytest 会把断言展开成 '429 = <Response ...>.status'，这是真频控。"""
        message = (
            "assert 429 < 400  where 429 = "
            "<Response url='https://shopify.com/authentication/x'>.status"
        )

        self.assertTrue(RATE_LIMIT_PATTERN.search(message))

    def test_bare_429_in_traceback_is_not_rate_limiting(self) -> None:
        """traceback 里出现 429 行号是完全正常的事，不能当频控证据。"""
        for message in (
            'File "home_page.py", line 429, in check',
            "assert 429 == 430",
            "locator resolved after 429 ms but was detached",
            "content-length 4290, got 429",
            "expected 429 items in gallery",
        ):
            self.assertIsNone(RATE_LIMIT_PATTERN.search(message), message)

    def test_ordinary_failures_are_not_rate_limiting(self) -> None:
        for message in (
            "AssertionError: cart badge should be 2, got 1",
            "Timeout 30000ms exceeded",
            "元素被遮挡：顶层元素=h2.jjb-banner__title",
        ):
            self.assertIsNone(RATE_LIMIT_PATTERN.search(message), message)

    def test_business_failure_with_429_line_number_stays_red(self) -> None:
        """端到端：traceback 含 line 429 的业务失败必须仍是红色卡片。"""
        # 用单引号包裹文件名，避免双引号破坏 XML 属性。
        detail = "File 'home_page.py', line 429, in check / banner missing"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "results.xml"
            path.write_text(
                '<?xml version="1.0"?>'
                '<testsuite name="pytest" tests="2" failures="1" errors="0"'
                ' skipped="0" time="12.0">'
                '<testcase classname="python_playwright.tests.test_cart"'
                ' name="test_badge[pc]" time="3.0">'
                f'<failure message="{detail}">{detail}</failure></testcase>'
                '<testcase classname="python_playwright.tests.test_cart"'
                ' name="test_ok[pc]" time="2.0"/></testsuite>',
                encoding="utf-8",
            )
            summary = read_results(str(path))

        self.assertEqual(summary["total"], 2, "XML 未被正确解析，测试自身有问题")

        self.assertEqual(summary["rate_limited"], 0)
        card = card_template(summary, exit_code="1")
        self.assertEqual(card["card"]["header"]["template"], "red")


class ExecutedPassRateTests(unittest.TestCase):
    """已执行通过率的分母必须是真正得出业务结论的用例数。"""

    def _rate(self, card) -> str:
        for element in card["card"]["elements"]:
            for field in element.get("fields", []):
                content = field["text"]["content"]
                if "已执行通过率" in content:
                    return content
        return ""

    def test_legacy_summary_cannot_exceed_one_hundred_percent(self) -> None:
        """旧格式报告曾算出 450%：分母被 rate_limited 过度扣减。"""
        summary = {
            "total": 10,
            "passed": 9,
            "failed": 1,
            "errors": 0,
            "skipped": 0,
            "rate_limited": 8,
            "duration": "1分0秒",
            "cases": [],
        }

        rate = self._rate(card_template(summary, exit_code="1"))

        self.assertIn("100.0%（9/9）", rate)
        self.assertNotIn("450", rate)

    def test_denominator_counts_passed_plus_business_failures(self) -> None:
        summary = {
            "total": 30,
            "passed": 12,
            "failed": 1,
            "errors": 0,
            "skipped": 17,
            "rate_limited": 17,
            "rate_limited_skipped": 17,
            "rate_limited_failures": 0,
            "ordinary_skipped": 0,
            "duration": "5分0秒",
            "cases": [],
        }

        rate = self._rate(card_template(summary, exit_code="1"))

        self.assertIn("92.3%（12/13）", rate)

    def test_zero_results_does_not_divide_by_zero(self) -> None:
        summary = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "rate_limited": 0,
            "duration": "0秒",
            "cases": [],
        }

        rate = self._rate(card_template(summary, exit_code="0"))

        self.assertIn("0.0%（0/0）", rate)


class FailedCaseListingTests(unittest.TestCase):
    """卡片必须直接回答"失败的是什么"，不用点开报告。"""

    def _summary_with(self, *cases) -> dict:
        return {
            "total": 21,
            "passed": 21 - len(cases),
            "failed": len(cases),
            "errors": 0,
            "skipped": 0,
            "rate_limited": 0,
            "rate_limited_skipped": 0,
            "rate_limited_failures": 0,
            "ordinary_skipped": 0,
            "duration_seconds": 1800,
            "modules": [],
            "failed_cases": list(cases),
            "cases": [],
        }

    def test_no_failures_renders_nothing(self) -> None:
        self.assertEqual(_failed_case_lines(self._summary_with()), "")

    def test_case_name_and_detail_are_listed(self) -> None:
        lines = _failed_case_lines(
            self._summary_with(
                {
                    "name": "test_cart_tc05_header_opens_full_cart[pc]",
                    "module": "购物车",
                    "detail": "AssertionError: Gallery 加购接口失败：HTTP 503",
                }
            )
        )

        self.assertIn("test_cart_tc05_header_opens_full_cart[pc]", lines)
        self.assertIn("购物车", lines)
        self.assertIn("HTTP 503", lines)

    def test_long_list_is_truncated_with_pointer_to_report(self) -> None:
        cases = [
            {"name": f"test_{index}", "module": "首页", "detail": "失败"}
            for index in range(12)
        ]

        lines = _failed_case_lines(self._summary_with(*cases), limit=8)

        self.assertIn("另有 4 条失败", lines)
        self.assertIn("HTML 报告", lines)

    def test_failed_cases_are_extracted_from_junit(self) -> None:
        detail = "AssertionError: Gallery 加购接口失败：HTTP 503"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "results.xml"
            path.write_text(
                '<?xml version="1.0"?>'
                '<testsuite name="pytest" tests="2" failures="1" errors="0"'
                ' skipped="0" time="60">'
                '<testcase classname="python_playwright.tests.test_cart"'
                ' name="test_cart_tc05_header_opens_full_cart[pc]" time="30">'
                f'<failure message="{detail}">{detail}</failure></testcase>'
                '<testcase classname="python_playwright.tests.test_cart"'
                ' name="test_ok[pc]" time="10"/></testsuite>',
                encoding="utf-8",
            )
            summary = read_results(str(path))

        self.assertEqual(len(summary["failed_cases"]), 1)
        entry = summary["failed_cases"][0]
        self.assertIn("tc05", entry["name"])
        self.assertEqual(entry["module"], "购物车")
        self.assertIn("503", entry["detail"])

    def test_rate_limited_failures_are_not_listed_as_business_failures(self) -> None:
        """429 频控不是业务失败，不应出现在失败用例列表里。"""
        detail = "站点访问频控（HTTP 429）：jujubit.ai/cart.js 未完成。"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "results.xml"
            path.write_text(
                '<?xml version="1.0"?>'
                '<testsuite name="pytest" tests="1" failures="1" errors="0"'
                ' skipped="0" time="10">'
                '<testcase classname="python_playwright.tests.test_cart"'
                ' name="test_add[pc]" time="5">'
                f'<failure message="{detail}">{detail}</failure></testcase>'
                "</testsuite>",
                encoding="utf-8",
            )
            summary = read_results(str(path))

        self.assertEqual(summary["failed_cases"], [])

    def test_card_shows_failure_section_and_report_button(self) -> None:
        summary = self._summary_with(
            {
                "name": "test_cart_tc05_header_opens_full_cart[pc]",
                "module": "购物车",
                "detail": "AssertionError: Gallery 加购接口失败：HTTP 503",
            }
        )
        report_url = (
            "https://github.com/o/r/blob/test-reports/cart/20260916/report.html?raw=1"
        )

        card = card_template(
            summary,
            "https://github.com/o/r/actions/runs/1",
            "https://github.com/o/r/artifacts/1",
            report_url,
            exit_code="1",
        )

        rendered = json.dumps(card, ensure_ascii=False)
        self.assertIn("失败用例", rendered)
        self.assertIn("tc05", rendered)
        buttons = [
            button
            for element in card["card"]["elements"]
            if element.get("tag") == "action"
            for button in element["actions"]
        ]
        # 运行页是主按钮：Job Summary 在那里，是唯一能在浏览器直接读的结论。
        # GitHub 对仓库内 HTML 强制 text/plain + nosniff，点开只有源码。
        primary = [b for b in buttons if b["type"] == "primary"]
        self.assertEqual(len(primary), 1)
        self.assertIn("运行摘要", primary[0]["text"]["content"])
        # HTML 报告仍提供，但措辞是"下载"而非"打开"。
        report_buttons = [b for b in buttons if b["url"] == report_url]
        self.assertEqual(len(report_buttons), 1)
        self.assertIn("下载", report_buttons[0]["text"]["content"])

    def test_card_omits_report_button_when_publish_failed(self) -> None:
        """发布步骤失败时链接为空，卡片仍应可用，只是没有该按钮。"""
        card = card_template(
            self._summary_with(),
            "https://github.com/o/r/actions/runs/1",
            "",
            "",
            exit_code="0",
        )

        buttons = [
            button
            for element in card["card"]["elements"]
            if element.get("tag") == "action"
            for button in element["actions"]
        ]
        labels = [button["text"]["content"] for button in buttons]
        self.assertNotIn("下载 HTML 报告", labels)
        # 运行摘要按钮必须仍在：Job Summary 是主要阅读入口。
        self.assertIn("查看运行摘要", labels)


class WebhookUrlValidationTests(unittest.TestCase):
    """报告正文含站点地址与失败详情，只允许发往飞书官方 HTTPS 域名。"""

    def test_official_feishu_and_lark_hosts_are_accepted(self) -> None:
        for url in (
            "https://open.feishu.cn/open-apis/bot/v2/hook/abc-123",
            "https://open.larksuite.com/open-apis/bot/v2/hook/abc-123",
            "https://OPEN.FEISHU.CN/open-apis/bot/v2/hook/abc-123",
        ):
            self.assertEqual(_validate_webhook_url(url), url)

    def test_non_https_scheme_is_rejected(self) -> None:
        for url in (
            "http://open.feishu.cn/open-apis/bot/v2/hook/abc",
            "file:///etc/passwd",
        ):
            with self.assertRaisesRegex(RuntimeError, "https"):
                _validate_webhook_url(url)

    def test_third_party_and_internal_hosts_are_rejected(self) -> None:
        """配错或被篡改的地址不能让脚本把报告 POST 到任意主机。"""
        for url in (
            "https://evil.example.com/hook",
            "https://127.0.0.1:8080/hook",
            "https://169.254.169.254/latest/meta-data/",
            "https://open.feishu.cn.evil.example.com/hook",
        ):
            with self.assertRaisesRegex(RuntimeError, "允许列表"):
                _validate_webhook_url(url)


if __name__ == "__main__":
    unittest.main()
