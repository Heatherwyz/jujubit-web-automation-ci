"""测试环境开关的离线守护：默认必须是线上链路。

背景：主题里有 ``isTest()``，认 ``localStorage._shop_mode === 'test'``。
打开它会让前端走测试环境分支（实验开关改走 overrideExperiment、部分入口
判定不同），与线上行为不一致。

所以这个开关只能显式打开，不能变成默认行为——否则日常回归拿测试链路的
结果当线上验收，失败和通过都不可信。用户 2026-09-20 明确要求过
inject_experiment 不得设 _shop_mode，这里把边界钉住。
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_CONFTEST = ROOT / "python_playwright" / "tests" / "conftest.py"
ROOT_CONFTEST = ROOT / "conftest.py"
RUN_ALL = ROOT / "run_all.py"
MEMBERSHIP_PAGE = ROOT / "python_playwright" / "pages" / "membership_page.py"


class _Config:
    """只实现 getoption 的最小 config。"""

    def __init__(self, mode: str):
        self._mode = mode
        self.asked: list[str] = []

    def getoption(self, name: str):
        self.asked.append(name)
        if name == "--pw-shop-mode":
            return self._mode
        raise KeyError(name)


class _Page:
    """记录 add_init_script 调用的最小 Page。"""

    def __init__(self):
        self.scripts: list[str] = []

    def add_init_script(self, script=None, **kwargs):
        self.scripts.append(script if script is not None else kwargs.get("script", ""))


def _apply(mode: str) -> _Page:
    from python_playwright.tests.conftest import _apply_shop_mode

    page = _Page()
    _apply_shop_mode(page, _Config(mode))
    return page


class ApplyShopModeTests(unittest.TestCase):
    def test_live_injects_nothing(self) -> None:
        """默认 live 时一行脚本都不能注入。"""
        page = _apply("live")

        self.assertEqual(page.scripts, [])

    def test_test_mode_sets_shop_mode(self) -> None:
        page = _apply("test")

        self.assertEqual(len(page.scripts), 1)
        self.assertIn("_shop_mode", page.scripts[0])
        self.assertIn("'test'", page.scripts[0])

    def test_uses_init_script_not_evaluate(self) -> None:
        """必须用 add_init_script：它对后续每次导航都生效。

        手工 evaluate + reload 只影响当前那一跳，点 Get 跳 Airwallex、
        切页签换 URL 之后标记就丢了。
        """
        page = _apply("test")

        self.assertIn("localStorage", page.scripts[0])
        # init script 在 about:blank 上会抛，必须自己吞掉。
        self.assertIn("catch", page.scripts[0])


class SwitchWiringTests(unittest.TestCase):
    def test_option_declared_with_live_default(self) -> None:
        source = ROOT_CONFTEST.read_text(encoding="utf-8")

        self.assertIn("--pw-shop-mode", source)
        idx = source.index("--pw-shop-mode")
        block = source[idx : idx + 400]
        self.assertIn('default="live"', block)
        self.assertIn('choices=("live", "test")', block)

    def test_page_fixture_applies_switch(self) -> None:
        source = UI_CONFTEST.read_text(encoding="utf-8")

        self.assertIn("_apply_shop_mode(current_page, request.config)", source)

    def test_run_all_exposes_shop_mode(self) -> None:
        source = RUN_ALL.read_text(encoding="utf-8")

        self.assertIn("--shop-mode", source)
        self.assertIn("--pw-shop-mode", source)
        idx = source.index("--shop-mode")
        self.assertIn('default="live"', source[idx : idx + 400])


class InjectExperimentBoundaryTests(unittest.TestCase):
    """inject_experiment 仍然不许自己设 _shop_mode。

    它只负责覆盖 Statsig 实验分组。要走测试环境请用 --pw-shop-mode test，
    这样一轮里的模式是统一且在命令行可见的，不会某几条用例偷偷不一样。
    """

    def test_inject_experiment_does_not_set_shop_mode(self) -> None:
        source = MEMBERSHIP_PAGE.read_text(encoding="utf-8")
        start = source.index("def inject_experiment")
        end = source.index("\n    def ", start + 10)
        body = source[start:end]

        self.assertIn("_statsig_override", body)
        self.assertNotIn(
            "setItem('_shop_mode'",
            body,
            "inject_experiment 不得设 _shop_mode，用 --pw-shop-mode test 代替",
        )


if __name__ == "__main__":
    unittest.main()
