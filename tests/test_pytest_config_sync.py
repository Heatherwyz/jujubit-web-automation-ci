"""两份 pytest 配置的 marker 必须一致。

仓库有两个配置：pyproject.toml 管默认收集（tests/ 离线单测），
pytest-playwright.ini 管线上 UI 回归（run_all.py 显式 -c 指定）。marker 需要
在两处各注册一遍，漏改的后果是某条路径上出现 PytestUnknownMarkWarning，
而 --strict-markers 下会直接变成收集失败。这条测试把"记得改两处"变成机器保证。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INI_PATH = ROOT / "pytest-playwright.ini"
PYPROJECT_PATH = ROOT / "pyproject.toml"


def _ini_markers() -> dict[str, str]:
    text = INI_PATH.read_text(encoding="utf-8")
    match = re.search(r"^markers\s*=\s*\n((?:[ \t]+\S.*\n)+)", text, re.MULTILINE)
    if not match:
        return {}
    markers: dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line:
            continue
        name, _, description = line.partition(":")
        markers[name.strip()] = description.strip()
    return markers


def _pyproject_markers() -> dict[str, str]:
    text = PYPROJECT_PATH.read_text(encoding="utf-8")
    match = re.search(r"^markers\s*=\s*\[(.*?)\]", text, re.MULTILINE | re.DOTALL)
    if not match:
        return {}
    markers: dict[str, str] = {}
    for entry in re.findall(r'"([^"]+)"', match.group(1)):
        name, _, description = entry.partition(":")
        markers[name.strip()] = description.strip()
    return markers


class MarkerSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ini = _ini_markers()
        self.pyproject = _pyproject_markers()

    def test_both_configs_declare_markers(self) -> None:
        """先确认解析成功，否则下面的比较会假通过。"""
        self.assertTrue(self.ini, "未能从 pytest-playwright.ini 解析出 markers")
        self.assertTrue(self.pyproject, "未能从 pyproject.toml 解析出 markers")

    def test_marker_names_match(self) -> None:
        only_ini = sorted(set(self.ini) - set(self.pyproject))
        only_pyproject = sorted(set(self.pyproject) - set(self.ini))

        self.assertEqual(
            (only_ini, only_pyproject),
            ([], []),
            "marker 未同步：仅在 ini 中="
            f"{only_ini}；仅在 pyproject 中={only_pyproject}",
        )

    def test_marker_descriptions_match(self) -> None:
        """描述也应一致，避免两份配置对同一 marker 给出不同说明。"""
        mismatched = {
            name: (self.ini[name], self.pyproject[name])
            for name in set(self.ini) & set(self.pyproject)
            if self.ini[name] != self.pyproject[name]
        }

        self.assertEqual(mismatched, {}, f"marker 描述不一致：{mismatched}")

    def test_known_markers_are_present(self) -> None:
        for name in ("cart_session", "cart_smoke", "html_contract"):
            self.assertIn(name, self.ini, name)
            self.assertIn(name, self.pyproject, name)


class TestPathScopeTests(unittest.TestCase):
    """默认配置只能收集 tests/，否则裸跑 pytest 会误访问线上站点。"""

    def test_pyproject_testpaths_is_offline_only(self) -> None:
        text = PYPROJECT_PATH.read_text(encoding="utf-8")
        match = re.search(r"^testpaths\s*=\s*\[(.*?)\]", text, re.MULTILINE)

        self.assertIsNotNone(match, "pyproject.toml 缺少 testpaths")
        paths = re.findall(r'"([^"]+)"', match.group(1))
        self.assertEqual(paths, ["tests"])

    def test_ini_testpaths_targets_ui_suite(self) -> None:
        text = INI_PATH.read_text(encoding="utf-8")
        match = re.search(r"^testpaths\s*=\s*(.+)$", text, re.MULTILINE)

        self.assertIsNotNone(match, "pytest-playwright.ini 缺少 testpaths")
        self.assertIn("python_playwright/tests", match.group(1))


if __name__ == "__main__":
    unittest.main()
