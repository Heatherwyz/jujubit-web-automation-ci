"""页面内可见性判定只允许有一份实现，且占位符必须被正确替换。

历史问题：cart_page.py 里 isRendered 有三份副本，其中两份只检查元素自身样式。
display:none 与 visibility:hidden 会被浏览器继承到子元素的 computed style，
但 opacity 不会——父元素 opacity:0 时子元素自身仍是 1。用最小 DOM 验证过 5 个
场景中 3 个判定相反：只检查自身的版本会把完全不可见的按钮判为可点击，
于是"点击成功"但用户根本看不到该控件。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from python_playwright.pages.cart_page import IS_RENDERED_JS

CART_PAGE_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "python_playwright"
    / "pages"
    / "cart_page.py"
).read_text(encoding="utf-8")

PLACEHOLDER = "__IS_RENDERED__"


class IsRenderedSingleSourceTests(unittest.TestCase):
    def test_only_one_definition_exists(self) -> None:
        """整个文件里 isRendered 只能定义一次，即模块级常量。"""
        definitions = re.findall(r"const isRendered = element => \{", CART_PAGE_SOURCE)

        self.assertEqual(
            len(definitions),
            1,
            "isRendered 出现了多份定义；请统一复用 IS_RENDERED_JS",
        )

    def test_placeholders_and_substitutions_are_balanced(self) -> None:
        """每个占位符都必须有配套的 .replace()，否则注入的 JS 会缺少函数定义。"""
        bare = len(
            re.findall(rf"^\s*{PLACEHOLDER}\s*$", CART_PAGE_SOURCE, re.MULTILINE)
        )
        replaces = len(
            re.findall(
                rf'\.replace\(\s*"{PLACEHOLDER}"\s*,\s*IS_RENDERED_JS\s*\)',
                CART_PAGE_SOURCE,
            )
        )

        self.assertEqual(
            bare,
            replaces,
            f"占位符 {bare} 处但 replace 只有 {replaces} 处，注入会缺少 isRendered",
        )
        self.assertGreater(bare, 0, "未找到任何占位符，替换机制可能已被改掉")


class IsRenderedSemanticsTests(unittest.TestCase):
    """锁定判定语义。这些是纯文本断言，浏览器行为已单独用真实 DOM 验证过。"""

    def test_walks_ancestors(self) -> None:
        """必须向上遍历祖先，否则父级 opacity:0 之下的元素会被误判为可见。"""
        self.assertIn("parentElement", IS_RENDERED_JS)
        self.assertRegex(IS_RENDERED_JS, r"for\s*\(\s*let node = element")

    def test_checks_display_visibility_and_opacity(self) -> None:
        for prop in ("display", "visibility", "opacity"):
            self.assertIn(prop, IS_RENDERED_JS, f"缺少 {prop} 判定")

    def test_opacity_threshold_excludes_near_invisible(self) -> None:
        """极小 opacity 视为不可见，避免把淡入动画的中间态当成已就绪。"""
        self.assertIn("<= 0.01", IS_RENDERED_JS)

    def test_requires_non_collapsed_box(self) -> None:
        """宽高需大于 1px，排除塌陷占位节点。"""
        self.assertIn("rect.width > 1", IS_RENDERED_JS)
        self.assertIn("rect.height > 1", IS_RENDERED_JS)

    def test_guards_null_element(self) -> None:
        self.assertIn("if (!element) return false;", IS_RENDERED_JS)

    def test_defines_the_expected_function_name(self) -> None:
        """注入脚本按 isRendered 这个名字调用，重命名会让所有调用点失效。"""
        self.assertIn("const isRendered = element =>", IS_RENDERED_JS)


if __name__ == "__main__":
    unittest.main()
