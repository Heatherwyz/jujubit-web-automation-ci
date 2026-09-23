"""已知问题豁免清单的约束（静态检查，不访问站点）。

已知问题用 xfail 而不是删断言或无条件跳过：
- 删断言会连另一端的保护一起丢（REQ-03 的 PC 端仍应硬断言）；
- 无条件跳过在报告里读不出"为什么没验证"；
- xfail 记为未完成并带原因，有效覆盖会如实扣减，不会伪装成通过。

这里锁住豁免机制本身：清单必须是可枚举的常量、必须只包含合法平台、且断言
逻辑不能被改成对所有端都放行。清单为空时表示已恢复全量断言。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from python_playwright import home_contract
from python_playwright.tests import test_home_requirements as ui_requirements

KNOWN_LAZY_HERO_PLATFORMS = ui_requirements.KNOWN_LAZY_HERO_PLATFORMS
# 用属性访问而不是 from ... import test_xxx：后者会让 pytest 把这个线上用例
# 当成本模块的离线用例收集，从而在没有浏览器 fixture 的情况下报 error。
_hero_test = ui_requirements.test_hero_lcp_media_is_eager

VALID_PLATFORMS = frozenset({"pc", "h5"})
SOURCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "python_playwright"
    / "tests"
    / "test_home_requirements.py"
)


class KnownLazyHeroTests(unittest.TestCase):
    def test_exemption_list_contains_only_valid_platforms(self) -> None:
        unexpected = sorted(KNOWN_LAZY_HERO_PLATFORMS - VALID_PLATFORMS)

        self.assertEqual(
            unexpected,
            [],
            f"豁免清单里有无效平台名：{unexpected}（只允许 pc / h5）",
        )

    def test_exemption_is_not_blanket(self) -> None:
        """不能把两端都豁免——那等于删掉这条用例。"""
        self.assertNotEqual(
            set(KNOWN_LAZY_HERO_PLATFORMS),
            set(VALID_PLATFORMS),
            "两端都豁免时这条用例已无保护作用，应直接删除或修复主题配置",
        )

    def _hero_ast(self) -> ast.FunctionDef:
        """从源文件解析该用例的 AST；不能用 getsource+cleandoc，那会破坏缩进。"""
        tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
        for node in tree.body:
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "test_hero_lcp_media_is_eager"
            ):
                return node
        raise AssertionError("未找到 test_hero_lcp_media_is_eager")

    def test_assertion_still_raises_for_non_exempt_platforms(self) -> None:
        """豁免之外的端必须仍然抛 AssertionError，而不是一律 xfail。"""
        node = self._hero_ast()
        source = ast.unparse(node)

        self.assertIn("raise AssertionError", source)
        self.assertIn("KNOWN_LAZY_HERO_PLATFORMS", source)

        xfail_calls = [
            call
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "xfail"
        ]
        self.assertEqual(len(xfail_calls), 1, "xfail 只应出现一次")

    def test_xfail_is_guarded_by_the_exemption_list(self) -> None:
        """xfail 必须在检查豁免清单的 if 分支内，不能无条件放行。"""
        for node in ast.walk(self._hero_ast()):
            if not isinstance(node, ast.If):
                continue
            test_source = ast.unparse(node.test)
            if "KNOWN_LAZY_HERO_PLATFORMS" not in test_source:
                continue
            body_source = ast.unparse(node.body)
            if "xfail" in body_source:
                return
        raise AssertionError(
            "未找到受 KNOWN_LAZY_HERO_PLATFORMS 守卫的 xfail 分支；"
            "豁免不能无条件生效"
        )

    def test_exemption_reason_names_the_followup(self) -> None:
        """豁免必须写清何时恢复，否则会变成永久性静默。"""
        source = ast.unparse(self._hero_ast())

        self.assertIn("KNOWN_LAZY_HERO_PLATFORMS", source)
        self.assertIn("eager", source)

    def test_constant_is_documented_with_discovery_context(self) -> None:
        """常量旁必须留下发现时间与结论，避免以后没人知道为什么豁免。"""
        text = SOURCE_PATH.read_text(encoding="utf-8")
        index = text.index("KNOWN_LAZY_HERO_PLATFORMS")
        preceding = text[max(0, index - 700) : index]

        self.assertIn("2026-09-15", preceding)
        self.assertIn("LCP", preceding)


class RetiredCategoryInSeoCopyTests(unittest.TestCase):
    """品类下线后，导航基准要删干净，SEO 文案债要留着被盯住。

    背景（2026-09-22）：Crystal Bracelets 下线，首页已无该品类入口，但
    title / description / og / twitter 文案仍在售卖它。两件事必须分开处理：

    - 导航基准删断言：需求取消就不该再有人为它放宽条件；
    - SEO 期望值保持与线上一致：擅自改成"正确文案"会让断言变红在我们自己
      改期望值上；擅自删掉该词，则线上文案再没有任何用例覆盖。
    """

    def test_retired_category_left_navigation_baseline(self) -> None:
        """已下线品类不得再出现在导航或品类链接基准里。"""
        for retired in home_contract.KNOWN_RETIRED_CATEGORY_IN_SEO_COPY:
            self.assertNotIn(
                retired,
                home_contract.EXPECTED_HEADER_CATEGORY_LINKS,
                f"{retired} 已下线，应从品类链接基准中删除而不是保留后放宽",
            )
            self.assertNotIn(
                retired,
                home_contract.EXPECTED_NAVIGATION_LINKS,
                f"{retired} 已下线，不应留在一级导航基准里",
            )

    def test_seo_copy_still_covered_by_assertions(self) -> None:
        """文案债必须仍被 title/description 断言覆盖，不能悄悄删词。"""
        for retired in home_contract.KNOWN_RETIRED_CATEGORY_IN_SEO_COPY:
            self.assertIn(
                retired,
                home_contract.EXPECTED_TITLE,
                f"{retired} 仍在线上 title 中；期望值删掉它就等于没人再盯这条文案",
            )
            self.assertIn(
                retired.lower(),
                home_contract.EXPECTED_DESCRIPTION.lower(),
                f"{retired} 仍在线上 description 中，期望值不应擅自去掉",
            )

    def test_debt_is_documented_with_followup(self) -> None:
        """常量旁要写清发现时间与处置方式，避免变成永久静默。"""
        text = (
            Path(__file__).resolve().parents[1]
            / "python_playwright"
            / "home_contract.py"
        ).read_text(encoding="utf-8")
        index = text.index("KNOWN_RETIRED_CATEGORY_IN_SEO_COPY")
        preceding = text[max(0, index - 900) : index]

        self.assertIn("2026-09-22", preceding)
        self.assertIn("SEO", preceding)


if __name__ == "__main__":
    unittest.main()
