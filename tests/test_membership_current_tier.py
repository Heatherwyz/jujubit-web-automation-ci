"""当前会员档位读取的离线单测。

为什么单独守：MEM-22 要按账号实际档位决定"验证还是记未完成"。最早的实现是扫
overview 可见文本找 Basic/Pro/Premium，但会员页权益区本身就写着
"Upgrade to Premium for more generations"——Basic 账号会被判成 Premium，
断言直接假过。改为读付费墙容器的 data-membership-plan 后，这里锁住映射规则，
包括 PRIME 是 PREMIUM 的历史别名。
"""

from __future__ import annotations

import unittest

from python_playwright.pages.membership_page import SEL_PAYWALL, MembershipPage


class _Locator:
    """只实现 count() 与 get_attribute() 的最小 Locator。"""

    def __init__(self, *, count: int, attrs: dict | None = None):
        self._count = count
        self._attrs = attrs or {}

    def count(self) -> int:
        return self._count

    @property
    def first(self) -> "_Locator":
        return self

    def get_attribute(self, name: str):
        return self._attrs.get(name)


class _Page:
    """只实现 current_tier() 需要的 locator 分派。"""

    def __init__(self, *, paywall: _Locator):
        self._paywall = paywall
        self.selectors: list[str] = []

    def locator(self, selector: str) -> _Locator:
        self.selectors.append(selector)
        if selector == SEL_PAYWALL:
            return self._paywall
        return _Locator(count=0)


def _page_with_plan(value, *, count: int = 1) -> _Page:
    attrs = {} if value is None else {"data-membership-plan": value}
    return _Page(paywall=_Locator(count=count, attrs=attrs))


def _tier_for(value, *, count: int = 1) -> str:
    page = _page_with_plan(value, count=count)
    mp = MembershipPage.__new__(MembershipPage)
    mp.page = page
    return MembershipPage.current_tier(mp)


class CurrentTierTests(unittest.TestCase):
    def test_reads_uppercase_plan_values(self) -> None:
        """线上该属性是大写：BASIC / PRO / PREMIUM。"""
        self.assertEqual(_tier_for("BASIC"), "Basic")
        self.assertEqual(_tier_for("PRO"), "Pro")
        self.assertEqual(_tier_for("PREMIUM"), "Premium")

    def test_prime_is_premium_alias(self) -> None:
        """PRIME 是 PREMIUM 的历史别名，必须归一到 Premium。

        漏了它会让 Premium 账号被判成"未识别"，MEM-22 永远跳过。
        """
        self.assertEqual(_tier_for("PRIME"), "Premium")

    def test_lowercase_and_padded_values_are_normalized(self) -> None:
        """Header 上同名属性是小写；两处取值大小写不一致，不能只认一种。"""
        self.assertEqual(_tier_for("basic"), "Basic")
        self.assertEqual(_tier_for("  premium  "), "Premium")

    def test_unknown_or_missing_value_returns_empty(self) -> None:
        """读不到就返回空串，由调用方记为未完成，不能猜一个档位。"""
        self.assertEqual(_tier_for(None), "")
        self.assertEqual(_tier_for(""), "")
        self.assertEqual(_tier_for("ENTERPRISE"), "")

    def test_absent_paywall_container_returns_empty(self) -> None:
        self.assertEqual(_tier_for("PREMIUM", count=0), "")

    def test_reads_paywall_container_not_overview_text(self) -> None:
        """必须查付费墙容器，不能回到扫 overview 文本的老写法。"""
        page = _page_with_plan("PREMIUM")
        mp = MembershipPage.__new__(MembershipPage)
        mp.page = page
        MembershipPage.current_tier(mp)

        self.assertIn(SEL_PAYWALL, page.selectors)


if __name__ == "__main__":
    unittest.main()
