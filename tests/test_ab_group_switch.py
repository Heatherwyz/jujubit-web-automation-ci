"""AB 实验分组开关的离线守护：默认不动分组，指定分组必须真的生效。

背景（2026-10-16 实测线上站点，两轮一致）：Statsig 把分组算在 stableID 上，
键名形如 ``statsig.stable_id.<hash>``。把它固定成 1/2/3 时：

- 1 命中 ``...:stableID:id_override`` 规则，返回 Control；
- 2 同样命中 id_override，返回 Test；
- 3 在 membership_entry_redirect、discount_badge_removal 上都没有覆盖规则，
  退化成按 ID 哈希分桶的随机结果，不是 Test2。

所以这里钉住两条边界：默认跑法不能被改掉（每日全量仍按线上分桶跑一遍，
不把用例乘以三）；指定分组时必须回读规则确认覆盖生效，没生效要如实报
未完成，不能拿哈希分桶的结果当验收过的分组。
"""

from __future__ import annotations

import unittest


class _Config:
    """只实现 getoption 的最小 config。"""

    def __init__(self, group: str):
        self._group = group
        self.asked: list[str] = []

    def getoption(self, name: str):
        self.asked.append(name)
        if name == "--pw-ab-group":
            return self._group
        raise KeyError(name)


class _Page:
    """记录 add_init_script 与 evaluate 的最小 Page。"""

    def __init__(self, experiment_state=None):
        self.scripts: list[str] = []
        self._experiment_state = experiment_state or {}

    def add_init_script(self, script=None, **kwargs):
        self.scripts.append(script if script is not None else kwargs.get("script", ""))

    def evaluate(self, script, arg=None):
        return self._experiment_state


def _apply(group: str) -> _Page:
    from python_playwright.tests.conftest import _apply_ab_group

    page = _Page()
    _apply_ab_group(page, _Config(group))
    return page


class ApplyAbGroupTests(unittest.TestCase):
    def test_default_injects_nothing(self) -> None:
        """默认不写 stableID，保持每日全量按线上分桶跑一遍。"""
        page = _apply("default")

        self.assertEqual(page.scripts, [])

    def test_group_sets_stable_id_and_clears_cache(self) -> None:
        """指定分组要写 stableID，并清掉旧分组缓存，否则 SDK 复用上一个分组。"""
        page = _apply("2")

        self.assertEqual(len(page.scripts), 1)
        script = page.scripts[0]
        self.assertIn("statsig.stable_id.", script)
        self.assertIn("'2'", script)
        self.assertIn("statsig.cached.evaluations.", script)
        self.assertIn("removeItem", script)

    def test_each_group_writes_its_own_value(self) -> None:
        for group in ("1", "2", "3"):
            with self.subTest(group=group):
                page = _apply(group)
                self.assertIn(f"'{group}'", page.scripts[0])

    def test_injection_runs_before_site_scripts(self) -> None:
        """必须用 add_init_script：分组在首次加载时就定了，写完再刷只影响下一跳。"""
        page = _apply("1")

        self.assertEqual(len(page.scripts), 1)
        self.assertIn("localStorage", page.scripts[0])


class RequireAbGroupTests(unittest.TestCase):
    """分组校验：覆盖规则没生效时必须如实报未完成。"""

    def _require(self, group: str, state: dict):
        import pytest

        from python_playwright.tests.conftest import require_ab_group

        page = _Page(experiment_state=state)
        try:
            require_ab_group(page, _Config(group), "membership_entry_redirect")
        except BaseException as exc:  # pytest.skip 抛的是 Skipped
            if isinstance(exc, pytest.skip.Exception):
                return str(exc)
            raise
        return None

    def test_default_group_skips_validation(self) -> None:
        """默认分组不校验，避免每日全量被这条逻辑挡住。"""
        reason = self._require("default", {})

        self.assertIsNone(reason)

    def test_override_hit_passes(self) -> None:
        """命中 id_override 且组名相符时放行。"""
        reason = self._require(
            "1",
            {
                "group": "Control",
                "rule": "5zzfRRvuvN6TpdJ3QDTFLR:stableID:id_override",
                "available": True,
            },
        )

        self.assertIsNone(reason)

    def test_hashed_bucket_reports_incomplete(self) -> None:
        """没配覆盖规则时是哈希分桶，必须报未完成而不是当成通过。"""
        reason = self._require(
            "3",
            {
                "group": "Control",
                "rule": "5zzfRRvuvN6TpdJ3QDTFLR",
                "available": True,
            },
        )

        self.assertIsNotNone(reason)
        self.assertIn("未完成", reason)
        self.assertIn("哈希分桶", reason)
        self.assertIn("stableID=3", reason)

    def test_group_name_mismatch_reports_incomplete(self) -> None:
        """命中覆盖但组名与约定不符时，不能假装验证过。"""
        reason = self._require(
            "1",
            {
                "group": "Test",
                "rule": "abc:stableID:id_override",
                "available": True,
            },
        )

        self.assertIsNotNone(reason)
        self.assertIn("未完成", reason)
        self.assertIn("Control", reason)

    def test_missing_client_reports_incomplete(self) -> None:
        """取不到 Statsig 客户端时同样报未完成。"""
        reason = self._require(
            "2",
            {"group": None, "rule": None, "available": False},
        )

        self.assertIsNotNone(reason)
        self.assertIn("未完成", reason)


class AbGroupNamingTests(unittest.TestCase):
    def test_group_numbering_matches_agreed_mapping(self) -> None:
        """用户定的口径：1 是 Control，2 是 Test，3 是 Test2。"""
        from python_playwright.tests.conftest import AB_GROUP_NAMES

        self.assertEqual(
            AB_GROUP_NAMES,
            {"1": "Control", "2": "Test", "3": "Test2"},
        )


class OctoberExperimentExpectationTests(unittest.TestCase):
    """10 月提测里两个按 stableID 分组的期望值。"""

    def test_paywall_visual_follows_group(self) -> None:
        """会员墙视觉：1 看旧版，2 看新版，未固定分组不限定。"""
        from python_playwright.tests.test_membership import PAYWALL_VARIANT_BY_GROUP

        self.assertEqual(PAYWALL_VARIANT_BY_GROUP, {"1": "legacy", "2": "visual"})
        self.assertNotIn("3", PAYWALL_VARIANT_BY_GROUP)

    def test_basic_generation_limit_drops_only_in_test_group(self) -> None:
        """免费生成次数：实验组 Basic 25 次，对照组与默认仍是 40。"""
        from python_playwright.pages.membership_page import (
            BASIC_DAILY_GENERATE_LIMIT_TEST_GROUP,
            DAILY_GENERATE_LIMITS,
        )

        self.assertEqual(DAILY_GENERATE_LIMITS["Basic"], 40)
        self.assertEqual(BASIC_DAILY_GENERATE_LIMIT_TEST_GROUP, 25)


if __name__ == "__main__":
    unittest.main()
