"""购物车脚本、报告标题与 Markdown 清单的离线同步测试。"""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

from python_playwright.cart_cases import CART_CASES
from python_playwright.tests.conftest import CASE_TITLES
from scripts.sync_cart_case_docs import DOCUMENT_PATH, render_cart_case_document


ROOT = Path(__file__).resolve().parents[1]
CART_TEST_PATH = ROOT / "python_playwright" / "tests" / "test_cart.py"


def _cart_test_functions(path: Path) -> tuple[str, ...]:
    """按源码顺序读取真实顶层购物车 pytest 函数。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return tuple(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_cart_")
    )


class CartCaseSyncTests(unittest.TestCase):
    """防止实现、报告和对外用例文档各自漂移。"""

    def test_real_cart_functions_match_structured_cases(self) -> None:
        expected = tuple(case.test_function for case in CART_CASES)

        self.assertEqual(_cart_test_functions(CART_TEST_PATH), expected)

    def test_cart_report_titles_match_structured_cases(self) -> None:
        expected = {
            case.test_function: case.report_title
            for case in CART_CASES
        }
        actual = {
            function_name: title
            for function_name, title in CASE_TITLES.items()
            if function_name.startswith("test_cart_")
        }

        self.assertEqual(tuple(actual), tuple(expected))
        self.assertEqual(actual, expected)

    def test_checked_in_markdown_matches_generated_document(self) -> None:
        self.assertEqual(
            DOCUMENT_PATH.read_text(encoding="utf-8"),
            render_cart_case_document(),
        )


if __name__ == "__main__":
    unittest.main()
