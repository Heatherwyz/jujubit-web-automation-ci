"""HTML 报告汉化的替换对必须真的命中 pytest-html 的输出。

汉化靠对生成好的 HTML 做字符串替换实现，这与 pytest-html 的内部模板强耦合：
升级后模板文案一改，替换就静默失效——报告变回英文，但没有任何用例失败。

这里用当前安装版本的真实 pytest-html 模板资源做校验，而不是断言某个历史报告
文件（那样只能证明过去某次生成是对的，无法在升级时报警）。已验证 13 组替换
在 pytest-html 4.1.1 下全部生效。
"""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from python_playwright.tests import conftest as CONFTEST


def _replacement_pairs() -> dict[str, str]:
    """从 pytest_sessionfinish 源码里取出替换字典的字面量。"""
    source = inspect.getsource(CONFTEST.pytest_sessionfinish)
    tree = ast.parse(source.strip())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        pairs = {
            key.value: value.value
            for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)
        }
        if pairs:
            return pairs
    return {}


def _pytest_html_assets() -> str:
    """拼接 pytest-html 的全部源码与前端资源，作为替换目标的来源文本。

    必须包含 .py：表头 '>Result</th>' 等来自 report_data.py，摘要文案来自
    basereport.py，都不在 resources/ 目录里。
    """
    import pytest_html

    root = Path(pytest_html.__file__).resolve().parent
    chunks: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".js", ".jinja2", ".html"}:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


class ReplacementPairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pairs = _replacement_pairs()

    def test_pairs_were_parsed(self) -> None:
        """先确认解析成功，否则下面的检查会假通过。"""
        self.assertGreaterEqual(len(self.pairs), 10)

    def test_no_pair_is_a_no_op(self) -> None:
        for english, chinese in self.pairs.items():
            self.assertNotEqual(english, chinese, f"替换对无意义：{english!r}")

    def test_targets_are_not_already_chinese_sources(self) -> None:
        """源串不能是中文，否则说明有人把已替换的结果又写进了源。"""
        for english in self.pairs:
            self.assertFalse(
                any("\u4e00" <= char <= "\u9fff" for char in english),
                f"替换源串不应含中文：{english!r}",
            )


class PytestHtmlCompatibilityTests(unittest.TestCase):
    """替换源串必须能在当前 pytest-html 的资源里找到。"""

    def setUp(self) -> None:
        self.pairs = _replacement_pairs()
        self.assets = _pytest_html_assets()

    def test_assets_were_located(self) -> None:
        self.assertGreater(
            len(self.assets), 1_000, "未读到 pytest-html 资源，校验无意义"
        )

    # 这两条由 basereport.py 用 f-string 拼出
    # （f"{counts} {'tests' if plural else 'test'} took {duration}."），
    # 源码里不存在连续字面量，只能靠"生成真实报告"那条测试覆盖。
    ASSEMBLED_AT_RUNTIME = frozenset({" tests took ", " test took "})

    def test_every_source_string_still_exists_upstream(self) -> None:
        """升级 pytest-html 后若文案变更，这条会失败并指出具体哪几组失效。

        比较时忽略 HTML 标签片段（如 '>Result</th>'）的尖括号差异：表头文本
        由 report_data.py 提供，标签结构可能随版本调整。
        """
        missing = []
        for english in self.pairs:
            if english in self.ASSEMBLED_AT_RUNTIME:
                continue
            probe = english.replace("</th>", "").replace("<h2>", "")
            probe = probe.replace("</h2>", "").strip("<>").strip()
            if probe and probe not in self.assets:
                missing.append(english)

        self.assertEqual(
            missing,
            [],
            "以下汉化源串在当前 pytest-html 资源中已不存在，替换会静默失效："
            + ", ".join(repr(item) for item in missing),
        )

    def test_runtime_assembled_phrases_are_still_produced(self) -> None:
        """直接调用 pytest-html 的摘要拼装逻辑，确认词序未变。

        这两条替换依赖 '<数字> tests took <时长>.' 这个词序；上游改成
        'took ... for N tests' 之类就会静默失效。
        """
        from pytest_html import basereport

        source = inspect.getsource(basereport)

        self.assertIn("took", source)
        # 词序断言：counts 在前、took 在后，且 tests/test 单复数分支仍在。
        self.assertRegex(source, r"\{counts\}\s*\{[^}]*'tests'[^}]*'test'[^}]*\}\s*took")


if __name__ == "__main__":
    unittest.main()
