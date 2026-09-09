"""首页关键入口真实点击逻辑的离线单元测试。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from python_playwright.pages.home_page import HomePage


class _InputDevice:
    def __init__(self):
        self.clicks = []

    def click(self, x, y):
        self.clicks.append((x, y))

    def tap(self, x, y):
        self.clicks.append((x, y))


class _Page:
    def __init__(self, has_touch=False):
        self.has_touch = has_touch
        self.mouse = _InputDevice()
        self.touchscreen = _InputDevice()

    def evaluate(self, script):
        self.last_page_script = script
        return self.has_touch


class _Locator:
    def __init__(self, result):
        self.first = self
        self.result = result
        self.waited = None
        self.script = ""

    def wait_for(self, **kwargs):
        self.waited = kwargs

    def evaluate(self, script):
        self.script = script
        return self.result


class _HeroLocator:
    def __init__(self, calls, name="root"):
        self.calls = calls
        self.name = name
        self.first = self

    def locator(self, selector):
        self.calls.append(("locator", self.name, selector))
        return _HeroLocator(self.calls, selector)

    def filter(self, **kwargs):
        self.calls.append(("filter", self.name, kwargs))
        return self


class _HeroPage(_Page):
    def __init__(self):
        super().__init__()
        self.calls = []

    def get_by_role(self, role, **kwargs):
        self.calls.append(("role", role, kwargs))
        return _HeroLocator(self.calls, "banner")

    def locator(self, selector):
        self.calls.append(("page_locator", selector))
        return _HeroLocator(self.calls, selector)


class _Assertions:
    def to_have_count(self, expected):
        assert expected == 1


class HomeInteractionTests(unittest.TestCase):
    def _home(self, has_touch=False):
        home = object.__new__(HomePage)
        home.page = _Page(has_touch=has_touch)
        return home

    def test_click_unobstructed_uses_mouse_at_verified_point(self):
        home = self._home()
        locator = _Locator({"point": {"x": 42.5, "y": 108}, "blocker": ""})

        home.click_unobstructed(locator, "Create 导航")

        self.assertEqual(home.page.mouse.clicks, [(42.5, 108)])
        self.assertEqual(home.page.touchscreen.clicks, [])
        self.assertIn("elementFromPoint", locator.script)
        self.assertIn("0.88", locator.script)

    def test_click_unobstructed_uses_touchscreen_for_h5(self):
        home = self._home(has_touch=True)
        locator = _Locator({"point": {"x": 168.5, "y": 110}, "blocker": ""})

        home.click_unobstructed(locator, "H5 Create 导航")

        self.assertEqual(home.page.touchscreen.clicks, [(168.5, 110)])
        self.assertEqual(home.page.mouse.clicks, [])

    def test_click_unobstructed_reports_blocker_instead_of_forcing_click(self):
        home = self._home(has_touch=True)
        locator = _Locator({"point": None, "blocker": "div.jjb-header__bar"})

        with self.assertRaisesRegex(
            AssertionError, "Create 导航无法真实点击.*div.jjb-header__bar"
        ):
            home.click_unobstructed(locator, "Create 导航")

        self.assertEqual(home.page.touchscreen.clicks, [])
        self.assertEqual(home.page.mouse.clicks, [])

    def test_active_hero_cta_uses_active_slide_and_explicit_cta_marker(self):
        home = object.__new__(HomePage)
        home.page = _HeroPage()

        with patch(
            "python_playwright.pages.home_page.expect",
            side_effect=lambda locator: _Assertions(),
        ):
            result = home.active_hero_cta()

        self.assertIsNotNone(result)
        self.assertIn(
            ("locator", "banner", "[data-banner-slide].is-active"),
            home.page.calls,
        )
        self.assertTrue(
            any(
                call[:2] == ("locator", "[data-banner-slide].is-active")
                and 'data-gtm-item="hero-cta"' in call[2]
                for call in home.page.calls
            )
        )
        self.assertTrue(
            any(
                call[0] == "page_locator" and ".jjb-banner__btn:visible" in call[1]
                for call in home.page.calls
            )
        )

    def test_login_case_source_filters_hidden_ab_variants(self):
        """登录入口必须只统计当前可见 A/B 变体，不能让隐藏按钮抢占分支。"""
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "python_playwright/tests/test_home_requirements.py"
        ).read_text(encoding="utf-8")

        self.assertGreaterEqual(source.count(".filter(visible=True)"), 2)
        self.assertIn("if not visible_buttons:", source)
        self.assertIn('href = href or "会员 Log In 按钮"', source)


if __name__ == "__main__":
    unittest.main()
