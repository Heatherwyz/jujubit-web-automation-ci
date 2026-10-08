"""购物车 banner 的 A/B 变体必须分别断言，不能一刀切改期望值。

2026-10-08 查实：线上同时跑两种变体，同一份代码多次访问会拿到不同的。

- ``control``（``.cc-membership-entry--control``）
  文案 ``Members: save $XX``，按 subtotal 的 20% 动态算，有 $20/$100 上下限。
  这正是 MEM-28/29/30 设计时验的规则。
- ``pro-price``（无 ``--control`` 后缀）
  文案 ``Save more with PRO for $19.9/mo.``，是固定会员月费，**不随 subtotal
  变化**，另有 ``__price`` / ``__offers`` 子节点展示券面额。换算规则在这个
  变体里根本不存在。

把期望值一刀切改成新文案，会在撞到 control 时失败；保留旧值则撞到新变体时
失败——CI 连续 8 轮各 6 条就是后者。所以按变体分别断言，两种都算通过。

另一个坑写在 test_variant_uses_same_visibility_rule_as_text：变体判定原来用
``offsetParent`` 判可见性，而 pro-price 实测 ``offsetParent=False``、
``rect.height=0``（外层容器折叠），于是同一轮里 ``banner_text()`` 有值、变体
却返回空串，把"已渲染"误判成"不在实验组"而全部 skip。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMBERSHIP_PAGE = ROOT / "python_playwright" / "pages" / "membership_page.py"
MEMBERSHIP_TESTS = ROOT / "python_playwright" / "tests" / "test_membership.py"


def _strip_leading_docstring(body: str) -> str:
    """只去掉方法开头的那个文档字符串，保留其余三引号内容。

    两个坑叠在一起，所以这个函数必须精确：

    1. 不剥会误报——这些方法的说明里恰好写着"原来用 offsetParent 判可见性"
       这类反面教材，扫全文会把说明当成违规代码。
    2. 剥光所有三引号又会把 ``page.evaluate(\"\"\"...\"\"\")`` 里的 JS 一起删掉，
       于是断言 innerText 存在的检查反而失败。

    写这条守护时两个坑都踩了一遍，所以只剥 ``def`` 行之后紧跟的那一个。
    """
    match = re.match(r'(\s*def [^\n]*\n\s*)""".*?"""', body, flags=re.S)
    if not match:
        return body
    return body[: match.end(1)] + body[match.end() :]


def _method_body(source: str, name: str) -> str:
    start = source.index(f"def {name}")
    rest = source[start:]
    end = rest.find("\n    def ")
    return rest if end == -1 else rest[:end]


def _method_code(source: str, name: str) -> str:
    """方法的可执行代码，不含开头的文档字符串。"""
    return _strip_leading_docstring(_method_body(source, name))


def _function_body(source: str, name: str) -> str:
    start = source.index(f"def {name}")
    rest = source[start:]
    end = rest.find("\ndef ")
    return rest if end == -1 else rest[:end]


class VariantDetectionTests(unittest.TestCase):
    SOURCE = MEMBERSHIP_PAGE.read_text(encoding="utf-8")

    def test_variant_helper_exists(self) -> None:
        self.assertIn("def cart_banner_variant", self.SOURCE)

    def test_distinguishes_control_from_pro_price(self) -> None:
        body = _method_body(self.SOURCE, "cart_banner_variant")

        self.assertIn("cc-membership-entry--control", body)
        self.assertIn("control", body)
        self.assertIn("pro-price", body)

    def test_variant_uses_same_visibility_rule_as_text(self) -> None:
        """变体判定不能用 offsetParent：pro-price 外层容器折叠，会误判成未渲染。

        必须和 banner_text() 一个口径——有文案就算渲染。
        """
        code = _method_code(self.SOURCE, "cart_banner_variant")

        self.assertNotIn(
            "offsetParent",
            code,
            "pro-price 变体 offsetParent=False，用它判定会把已渲染误判成未渲染",
        )
        self.assertIn("innerText", code)


class VariantAwareAssertionTests(unittest.TestCase):
    SOURCE = MEMBERSHIP_TESTS.read_text(encoding="utf-8")

    def test_shared_helper_branches_on_variant(self) -> None:
        body = _function_body(self.SOURCE, "_assert_cart_banner")

        self.assertIn("cart_banner_variant()", body)
        self.assertIn('== "control"', body)
        self.assertIn("expected_banner_copy", body)

    def test_pro_price_branch_checks_its_own_structure(self) -> None:
        """新变体验会员月费与券面额，不套旧的 20% 换算规则。"""
        body = _function_body(self.SOURCE, "_assert_cart_banner")
        # 月费形如 $19.9/mo.，券面额形如 $20 OFF / 20% OFF
        self.assertRegex(body, r"/\s*\\s\*mo|mo\b")
        self.assertIn("OFF", body)

    def test_cases_go_through_shared_helper(self) -> None:
        """三条换算用例都走同一个分支逻辑，避免只改其中一条。"""
        for name in (
            "test_mem28_cart_banner_20",
            "test_mem29_cart_banner_dynamic",
            "test_mem30_cart_banner_save_more",
        ):
            body = _function_body(self.SOURCE, name)
            self.assertIn(
                "_assert_cart_banner",
                body,
                f"{name} 必须走变体感知的共用断言",
            )

    def test_action_text_only_asserted_for_control(self) -> None:
        """pro-price 整块是可点区域，没有独立 Upgrade 按钮。"""
        body = _function_body(self.SOURCE, "test_mem31_checkout_banner_entry_page")

        self.assertIn("cart_banner_variant()", body)
        self.assertIn("BANNER_ACTION_TEXT", body)
        # entry_page 契约两种变体都该成立，不能被塞进 control 分支里
        action_at = body.index("BANNER_ACTION_TEXT")
        entry_at = body.index("banner_entry_page()")
        self.assertLess(
            action_at,
            entry_at,
            "entry_page 断言应在变体分支之外，两种变体都要验",
        )


class ExpectedCopyRuleTests(unittest.TestCase):
    """control 变体的换算规则本身不变，继续钉住。"""

    def test_control_copy_rule_unchanged(self) -> None:
        from python_playwright.pages.membership_page import (
            BANNER_SAVE_MORE_TEXT,
            expected_banner_copy,
        )

        self.assertEqual(expected_banner_copy(5_000), "Members: save $20")
        self.assertEqual(expected_banner_copy(25_000), "Members: save $50")
        self.assertEqual(
            expected_banner_copy(50_000, 10_001), BANNER_SAVE_MORE_TEXT
        )


if __name__ == "__main__":
    unittest.main()
