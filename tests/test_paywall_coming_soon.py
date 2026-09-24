"""付费墙 Coming Soon 必须判未完成，不能误报业务失败。

2026-09-25 实测：`--pw-shop-mode test` 下测试环境的付费墙整体是
"Coming Soon…… Go Back" —— 容器带 `is-coming-soon`，并盖一层 900px 全屏遮罩
`.jjb-membership-paywall__coming-soon`（z-index 20、pointerEvents auto）。
三张卡片在 DOM 里但全部被挡住点不动，于是 22 条交互用例集体报
"优惠弹窗关闭后仍在遮挡页面操作"，看起来像站点坏了。

实际是这个环境还没放开会员功能，属于未完成。两个口径的处置完全不同：
业务失败要查站点，未完成只说明该环境不具备验证条件。

踩过的两个坑都钉在这里：
1. 先 wait_for_selector 再查遮罩 —— 遮罩让卡片永远不可见，必然耗满 30 秒
   超时，检测代码根本执行不到。
2. 只在开头查一次 —— is-coming-soon 是 JS 后加的，同一轮里 MEM-01 命中、
   MEM-09 漏判。必须与卡片数量一起轮询。
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMBERSHIP_PAGE = ROOT / "python_playwright" / "pages" / "membership_page.py"
UI_CONFTEST = ROOT / "python_playwright" / "tests" / "conftest.py"


class _Page:
    """只实现 evaluate / locator 的最小 Page。"""

    def __init__(self, *, coming_soon: bool, cards: int = 3):
        self._coming_soon = coming_soon
        self._cards = cards
        self.waits = 0

    def evaluate(self, script, arg=None):
        return self._coming_soon

    def locator(self, selector):
        page = self

        class _Loc:
            def count(self):
                return page._cards

        return _Loc()

    def wait_for_selector(self, selector, timeout=None):
        return None

    def wait_for_timeout(self, ms):
        self.waits += 1


def _wait(coming_soon: bool, cards: int = 3):
    from python_playwright.pages.membership_page import MembershipPage

    mp = MembershipPage.__new__(MembershipPage)
    mp.page = _Page(coming_soon=coming_soon, cards=cards)
    MembershipPage.wait_for_paywall(mp, timeout=1_000)


class ComingSoonDetectionTests(unittest.TestCase):
    def test_raises_not_launched_when_coming_soon(self) -> None:
        from python_playwright.pages.membership_page import MembershipNotLaunchedError

        with self.assertRaises(MembershipNotLaunchedError) as ctx:
            _wait(coming_soon=True)

        self.assertIn("Coming Soon", str(ctx.exception))

    def test_returns_normally_when_paywall_live(self) -> None:
        """线上模式（没有遮罩、卡片齐）必须正常返回。"""
        _wait(coming_soon=False)

    def test_not_launched_is_not_login_error(self) -> None:
        """两类未完成原因要分开，处置动作不同。"""
        from python_playwright.pages.membership_page import (
            MembershipLoginRequiredError,
            MembershipNotLaunchedError,
        )

        self.assertFalse(
            issubclass(MembershipNotLaunchedError, MembershipLoginRequiredError)
        )
        self.assertFalse(
            issubclass(MembershipLoginRequiredError, MembershipNotLaunchedError)
        )


class WaitOrderTests(unittest.TestCase):
    """检测必须与卡片轮询交织，不能先等可见、也不能只查一次。"""

    SOURCE = MEMBERSHIP_PAGE.read_text(encoding="utf-8")

    def _body(self) -> str:
        start = self.SOURCE.index("def wait_for_paywall")
        end = self.SOURCE.index("\n    def ", start + 10)
        return self.SOURCE[start:end]

    def test_checks_coming_soon_inside_poll_loop(self) -> None:
        body = self._body()
        loop_at = body.index("while time.monotonic()")
        after_loop = body[loop_at:]

        self.assertIn(
            "paywall_coming_soon()",
            after_loop,
            "必须在轮询循环内检测：is-coming-soon 是 JS 后加的，只查一次会漏",
        )

    def test_does_not_wait_for_visible_cards_first(self) -> None:
        """30 秒级的 wait_for_selector 不能出现在首次检测之前。"""
        body = self._body()
        first_check = body.index("paywall_coming_soon()")
        head = body[:first_check]

        self.assertNotIn(
            f"wait_for_selector(SEL_CARD, timeout=timeout)",
            head,
            "先等卡片可见会耗满超时，遮罩下卡片永远不可见",
        )


class SkipConversionTests(unittest.TestCase):
    """hook 统一把这个异常转成 skip，16 处调用点不必各写 try/except。"""

    def test_hook_converts_to_skip(self) -> None:
        source = UI_CONFTEST.read_text(encoding="utf-8")

        self.assertIn("MembershipNotLaunchedError", source)
        idx = source.index("def pytest_runtest_makereport")
        body = source[idx : idx + 1600]
        self.assertIn("errisinstance(MembershipNotLaunchedError)", body)
        self.assertIn('report.outcome = "skipped"', body)


if __name__ == "__main__":
    unittest.main()
