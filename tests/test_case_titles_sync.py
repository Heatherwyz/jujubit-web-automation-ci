"""CASE_TITLES 必须与线上用例函数一一对应。

首页用例的中文标题是手工维护的 dict（购物车那边由 CART_CASES_BY_FUNCTION
自动生成）。漏加标题时报告会显示原始函数名，删用例忘删标题则留下无效残留。
两种都不会让任何用例失败，所以只能靠这条测试兜住。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from python_playwright.tests.conftest import CASE_TITLES

TESTS_DIR = Path(__file__).resolve().parents[1] / "python_playwright" / "tests"


def _declared_test_functions() -> set[str]:
    names: set[str] = set()
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        names.update(re.findall(r"^def (test_\w+)", source, re.MULTILINE))
    return names


class CaseTitleSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.functions = _declared_test_functions()

    def test_test_files_were_found(self) -> None:
        """先确认扫描到了用例，否则下面两条会假通过。"""
        self.assertGreater(len(self.functions), 20)

    def test_every_test_function_has_a_chinese_title(self) -> None:
        missing = sorted(self.functions - set(CASE_TITLES))

        self.assertEqual(
            missing,
            [],
            "以下用例缺少 CASE_TITLES 标题，报告会显示原始函数名：" + ", ".join(missing),
        )

    def test_no_stale_titles_remain(self) -> None:
        stale = sorted(set(CASE_TITLES) - self.functions)

        self.assertEqual(
            stale,
            [],
            "以下 CASE_TITLES 条目对应的用例已不存在，请删除：" + ", ".join(stale),
        )

    def test_titles_are_non_empty_strings(self) -> None:
        for name, title in CASE_TITLES.items():
            self.assertIsInstance(title, str, name)
            self.assertTrue(title.strip(), f"{name} 的标题为空")


if __name__ == "__main__":
    unittest.main()
