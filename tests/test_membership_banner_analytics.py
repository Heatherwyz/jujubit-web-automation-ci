"""会员引流入口与埋点事件的契约守护（离线，不访问站点）。

背景（2026-09-23 核实）：C 类的 MEM-26/33 曾把购物车会员 banner 判成"未上线"，
MEM-40/41/43 全部无条件 skip。读主题 `custom-cart.js` 和 `jjb-membership.js`
后发现都是误判——banner 真实类名是 `.cc-membership-entry`，埋点事件名也一直存在，
只是用例拿不到真实事件名、选择器又找错位置，才全部退化成"未实现"。

这里把两件容易悄悄改回去的事钉死：

1. banner 文案换算规则（下限 $20、上限 $100、折扣超 $100 转 save more）必须有
   离线覆盖，否则哪天有人改了 `expected_banner_copy` 的系数，文案用例会一起错。
2. 埋点事件名常量必须与主题源码保持一致；拦截必须真的拦住了
   （`__jjbWrapped`），否则断言的是"我们的 mock"，不是主题的上报行为。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from python_playwright.pages.membership_page import (
    BANNER_FALLBACK_TEXT,
    BANNER_SAVE_MORE_TEXT,
    EVENT_CART_ENTRY_CLICK,
    EVENT_ENTRY_VIEW,
    EVENT_PLAN_CLICK,
    EVENT_PLAN_IMPRESSION,
    expected_banner_copy,
)

PAGE_OBJECT = (
    Path(__file__).resolve().parents[1]
    / "python_playwright"
    / "pages"
    / "membership_page.py"
)


class BannerCopyRuleTests(unittest.TestCase):
    def test_floor_and_ceiling(self) -> None:
        """下限 $20、上限 $100。"""
        self.assertEqual(expected_banner_copy(5_000), "Members: save $20")
        self.assertEqual(expected_banner_copy(100), "Members: save $20")
        self.assertEqual(expected_banner_copy(50_000), "Members: save $100")
        self.assertEqual(expected_banner_copy(1_000_000), "Members: save $100")

    def test_proportional_middle_range(self) -> None:
        """区间内按 20% 折算。"""
        self.assertEqual(expected_banner_copy(25_000), "Members: save $50")

    def test_cents_format(self) -> None:
        """非整元保留两位小数，与主题的 formatMoney 一致。"""
        self.assertEqual(expected_banner_copy(12_345), "Members: save $24.69")

    def test_discount_over_hundred_shows_save_more(self) -> None:
        """折扣已超 $100 时不再算百分比，固定文案。"""
        self.assertEqual(expected_banner_copy(50_000, 10_001), BANNER_SAVE_MORE_TEXT)
        # 边界：折扣恰好 $100 不算"超"，仍按比例显示。
        self.assertEqual(expected_banner_copy(50_000, 10_000), "Members: save $100")

    def test_unreadable_amount_falls_back(self) -> None:
        """读不到金额（0 或负数）回退到固定文案。"""
        self.assertEqual(expected_banner_copy(0), BANNER_FALLBACK_TEXT)
        self.assertEqual(expected_banner_copy(-100), BANNER_FALLBACK_TEXT)


class AnalyticsEventNameTests(unittest.TestCase):
    """事件名常量必须与主题源码一致，否则断言和真实上报对不上。"""

    def test_event_names_match_theme_source(self) -> None:
        """三个事件名取自 jjb-membership.js / custom-cart.js，不能拼错。"""
        self.assertEqual(EVENT_ENTRY_VIEW, "membership_entry_view")
        self.assertEqual(EVENT_PLAN_IMPRESSION, "membership_plan_impression")
        self.assertEqual(EVENT_PLAN_CLICK, "membership_plan_click")
        self.assertEqual(EVENT_CART_ENTRY_CLICK, "membership_entry_click")

    def test_constants_are_documented_in_page_object(self) -> None:
        """常量必须落在页面对象里，供用例和守护测试共用，不散落在用例体内。"""
        source = PAGE_OBJECT.read_text(encoding="utf-8")
        for name in (
            EVENT_ENTRY_VIEW,
            EVENT_PLAN_IMPRESSION,
            EVENT_PLAN_CLICK,
        ):
            self.assertIn(f'"{name}"', source)

    def test_interception_marks_wrapped_logger(self) -> None:
        """埋点拦截必须真的包住 zlog.track，否则断言的是我们自己的 mock。

        早期实现只在赋值那一刻包一次，zlog 初始化后又重新赋 track，包装被覆盖，
        表现是 `__jjbWrapped` 为 true 但一条事件都收不到。现在的实现要守住
        track 这个属性本身——谁再赋值都会被重新包一层。
        """
        source = PAGE_OBJECT.read_text(encoding="utf-8")
        self.assertIn("__jjbTrackedEvents", source)
        self.assertIn("__jjbWrapped", source)
        # 关键接线：defineProperty 拦截 track 的 set，而不是只包一次。
        self.assertIn("defineProperty(target, 'track'", source)
        self.assertIn("set: (value) =>", source)

    def test_cart_entry_injection_enables_the_flag(self) -> None:
        """构造购物车金额时必须把入口开关置真，否则 membershipEntryHtml 恒返回空串。

        `_membershipCartEntryEnabled` 由服务端实验分配决定、测试侧改不了；不置真
        的话 4 条购物车 banner 用例会稳定拿到空 banner、误判成"未上线"。
        """
        source = PAGE_OBJECT.read_text(encoding="utf-8")
        self.assertIn("_membershipCartEntryEnabled = true", source)


if __name__ == "__main__":
    unittest.main()
