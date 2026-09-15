"""线上套件的 fixture 装配约束（静态检查，不访问站点）。

背景：契约层的 home_server_html fixture 曾自己调 sync_playwright() 创建第二个
同步运行时，与 conftest 里 session 级的 playwright_runtime 冲突，报
"Sync API inside the asyncio loop"。

这个 bug 的特点是**单独跑任一层都正常，只有同一进程混跑才炸**：
  pytest test_home_html_contract.py            -> 9 passed
  pytest test_home_requirements.py             -> 16 passed
  pytest test_home_requirements.py 加上契约层    -> 9 errors

而 CI 的 --collect-only 只做收集，不装配 fixture，也抓不到。真正混跑需要访问
线上站点，不适合放进离线层。因此这里做静态检查：禁止在线上测试模块里自建
Playwright 运行时，必须复用 conftest 提供的 playwright_runtime。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_TESTS_DIR = ROOT / "python_playwright" / "tests"
CONFTEST_PATH = UI_TESTS_DIR / "conftest.py"

# 只有 conftest 可以创建运行时；其余模块必须复用它的 fixture。
RUNTIME_FIXTURE = "playwright_runtime"


def _ui_test_modules() -> list[Path]:
    return sorted(UI_TESTS_DIR.glob("test_*.py"))


def _calls_sync_playwright(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "sync_playwright":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "sync_playwright":
            return True
    return False


class RuntimeOwnershipTests(unittest.TestCase):
    def test_ui_test_modules_were_found(self) -> None:
        """先确认扫到了模块，否则下面的检查会假通过。"""
        self.assertGreaterEqual(len(_ui_test_modules()), 3)

    def test_only_conftest_creates_the_playwright_runtime(self) -> None:
        offenders = []
        for path in _ui_test_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if _calls_sync_playwright(tree):
                offenders.append(path.name)

        self.assertEqual(
            offenders,
            [],
            "以下线上测试模块自建了 Playwright 运行时，与 conftest 的 "
            f"{RUNTIME_FIXTURE} 冲突（混跑时报 Sync API inside the asyncio "
            "loop）：" + ", ".join(offenders),
        )

    def test_conftest_still_provides_the_runtime_fixture(self) -> None:
        tree = ast.parse(CONFTEST_PATH.read_text(encoding="utf-8"))
        names = {
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }

        self.assertIn(RUNTIME_FIXTURE, names)


class ContractFixtureTests(unittest.TestCase):
    """契约层 fixture 必须声明依赖 playwright_runtime，而不是自己造。"""

    def _contract_fixture(self) -> ast.FunctionDef:
        path = UI_TESTS_DIR / "test_home_html_contract.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "home_server_html":
                return node
        raise AssertionError("未找到 home_server_html fixture")

    def test_declares_runtime_dependency(self) -> None:
        args = {arg.arg for arg in self._contract_fixture().args.args}

        self.assertIn(
            RUNTIME_FIXTURE,
            args,
            f"home_server_html 必须把 {RUNTIME_FIXTURE} 作为参数注入",
        )

    def test_does_not_create_its_own_runtime(self) -> None:
        self.assertFalse(_calls_sync_playwright(self._contract_fixture()))

    def test_disposes_the_request_context(self) -> None:
        """复用共享运行时后，自己创建的 request context 仍需释放。"""
        source = ast.unparse(self._contract_fixture())

        self.assertIn("dispose()", source)
        self.assertIn("finally", source)


if __name__ == "__main__":
    unittest.main()
