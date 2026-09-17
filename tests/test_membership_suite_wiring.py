"""会员模块的接线校验：marker、CASE_TITLES、套件选择口径。

这些都是"漏改一处就静默失效"的地方：
- marker 未在两份 pytest 配置注册 → PytestUnknownMarkWarning，--strict-markers 下直接失败
- CASE_TITLES 漏加 → 报告显示原始函数名
- 默认回归的 marker 表达式漏排除 membership → 默认跑会跑到需登录态的会员用例
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from python_playwright.membership_cases import (
    MEMBERSHIP_CASES,
    MEMBERSHIP_CASES_BY_FUNCTION,
    MEMBERSHIP_CASE_TITLES,
)
from python_playwright.tests.conftest import CASE_TITLES

ROOT = Path(__file__).resolve().parents[1]
MEMBERSHIP_TEST_FILE = ROOT / "python_playwright" / "tests" / "test_membership.py"
RUN_ALL = ROOT / "run_all.py"


def _declared_membership_functions() -> set[str]:
    source = MEMBERSHIP_TEST_FILE.read_text(encoding="utf-8")
    return set(re.findall(r"^def (test_\w+)", source, re.MULTILINE))


class CaseMetadataTests(unittest.TestCase):
    def test_cases_were_defined(self) -> None:
        self.assertGreaterEqual(len(MEMBERSHIP_CASES), 40)

    def test_case_ids_are_unique(self) -> None:
        ids = [case.case_id for case in MEMBERSHIP_CASES]

        self.assertEqual(len(ids), len(set(ids)))

    def test_function_names_are_unique(self) -> None:
        names = [case.function_name for case in MEMBERSHIP_CASES]

        self.assertEqual(len(names), len(set(names)))

    def test_every_declared_test_has_metadata(self) -> None:
        """测试文件里的每个函数都要有元数据，否则报告显示函数名。"""
        declared = _declared_membership_functions()
        missing = sorted(declared - set(MEMBERSHIP_CASES_BY_FUNCTION))

        self.assertEqual(
            missing,
            [],
            "以下会员用例缺少 membership_cases.py 元数据：" + ", ".join(missing),
        )

    def test_no_stale_metadata(self) -> None:
        """元数据里不应有已删除的函数。"""
        declared = _declared_membership_functions()
        stale = sorted(set(MEMBERSHIP_CASES_BY_FUNCTION) - declared)

        self.assertEqual(
            stale,
            [],
            "以下元数据对应的用例已不存在：" + ", ".join(stale),
        )

    def test_titles_carry_case_id(self) -> None:
        """报告标题应带 MEM-xx 编号，便于与手工用例对照。"""
        for case in MEMBERSHIP_CASES:
            self.assertTrue(
                case.report_title.startswith(case.case_id),
                f"{case.function_name} 的标题应以 {case.case_id} 开头",
            )


class CaseTitleWiringTests(unittest.TestCase):
    def test_membership_titles_are_merged_into_case_titles(self) -> None:
        """conftest 的 CASE_TITLES 必须包含全部会员标题。"""
        missing = sorted(set(MEMBERSHIP_CASE_TITLES) - set(CASE_TITLES))

        self.assertEqual(missing, [])

    def test_titles_match_metadata(self) -> None:
        for name, title in MEMBERSHIP_CASE_TITLES.items():
            self.assertEqual(CASE_TITLES[name], title)


class MarkerRegistrationTests(unittest.TestCase):
    """两份 pytest 配置都要注册 membership 与 membership_session。"""

    REQUIRED = ("membership", "membership_session")

    def test_ini_registers_markers(self) -> None:
        text = (ROOT / "pytest-playwright.ini").read_text(encoding="utf-8")
        for marker in self.REQUIRED:
            # 需要 MULTILINE：marker 是缩进的续行，不在字符串开头。
            self.assertTrue(
                re.search(rf"^\s+{marker}:", text, re.MULTILINE),
                f"pytest-playwright.ini 缺 {marker}",
            )

    def test_pyproject_registers_markers(self) -> None:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        for marker in self.REQUIRED:
            self.assertIn(f'"{marker}:', text, f"pyproject.toml 缺 {marker}")

    def test_module_level_marker_applied(self) -> None:
        """整个会员模块打 membership marker，run_all 才能用 -m 选中。"""
        source = MEMBERSHIP_TEST_FILE.read_text(encoding="utf-8")

        self.assertIn("pytestmark = pytest.mark.membership", source)

    def test_contract_file_also_marked(self) -> None:
        contract = (
            ROOT / "python_playwright" / "tests" / "test_membership_html_contract.py"
        ).read_text(encoding="utf-8")

        self.assertIn("pytest.mark.membership", contract)


class DefaultSuiteScopeTests(unittest.TestCase):
    """默认回归不能跑会员模块：会员用例需登录态，且支付要拉起第三方表单。"""

    def test_default_marker_excludes_membership(self) -> None:
        from run_all import DEFAULT_MARKER_EXPRESSION

        self.assertIn("not membership", DEFAULT_MARKER_EXPRESSION)
        self.assertIn("not cart_session", DEFAULT_MARKER_EXPRESSION)

    def test_run_all_exposes_membership_flags(self) -> None:
        text = RUN_ALL.read_text(encoding="utf-8")

        self.assertIn("--membership", text)
        self.assertIn("--membership-only", text)

    def test_membership_only_rejects_cart_flags(self) -> None:
        """两个套件的登录态与副作用不同，不应混跑。"""
        text = RUN_ALL.read_text(encoding="utf-8")

        self.assertIn("--membership-only 不能与任何购物车参数同时使用", text)


class PaymentBoundaryTests(unittest.TestCase):
    """支付用例必须停在"拉起表单"，不能真的付款。"""

    def test_no_pay_now_click_in_tests(self) -> None:
        source = MEMBERSHIP_TEST_FILE.read_text(encoding="utf-8")
        lowered = source.lower()

        # 不应出现点击 Pay Now / 提交支付的动作
        for forbidden in ("pay_now", "click_pay", "submit_payment"):
            self.assertNotIn(
                forbidden,
                lowered,
                f"会员用例不应包含 {forbidden}——支付只走到表单可见",
            )

    def test_payment_boundary_documented(self) -> None:
        source = MEMBERSHIP_TEST_FILE.read_text(encoding="utf-8")

        self.assertIn("不填卡", source)
        self.assertIn("不点 Pay Now", source)

    def test_page_object_has_no_card_filling(self) -> None:
        """页面对象不应提供填卡方法，避免误用产生真实扣款。"""
        page_source = (
            ROOT / "python_playwright" / "pages" / "membership_page.py"
        ).read_text(encoding="utf-8")

        for forbidden in ("def fill_card", "def submit_payment", "def pay_now"):
            self.assertNotIn(forbidden, page_source)

    def test_no_hardcoded_card_number_in_code(self) -> None:
        """测试卡号只应出现在文档里，不写进代码。"""
        for path in (
            MEMBERSHIP_TEST_FILE,
            ROOT / "python_playwright" / "pages" / "membership_page.py",
        ):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("4035", text, f"{path.name} 不应硬编码测试卡号")


if __name__ == "__main__":
    unittest.main()
