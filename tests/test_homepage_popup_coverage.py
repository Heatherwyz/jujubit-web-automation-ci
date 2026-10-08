"""首页关弹窗必须覆盖全部三种遮罩，漏一种就会整层点不动。

2026-10-08 查实：CI 连续 8 轮全量回归失败，购物车层 21 条全败，报错清一色是
"点击 Header Create 失败：控件中心被其他元素遮挡，遮挡元素=div.jjb-membership-offer"。

根因是 HomePage 的关弹窗逻辑只认 newsletter-popup-*，而会员 offer 弹窗
（.jjb-membership-offer）是后来才上线的第三种遮罩，首页层没跟上。它在本机
常不弹、CI 必弹，所以靠手工复现验不出来，只能用选择器兜住。

三处必须同时覆盖，漏任一处的后果都不同：
- popup_root / welcome_popup：定位不到就谈不上关
- _popup_blocks_interaction：检测不到遮挡，用例直接撞点击超时
- _popup_close_controls：能检测到却关不掉，白等 3 秒再失败
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME_PAGE = ROOT / "python_playwright" / "pages" / "home_page.py"

# 三种遮罩的根选择器。少一种就有一整类弹窗关不掉。
REQUIRED_ROOTS = (
    ".newsletter-popup-v2",
    ".newsletter-popup--original",
    ".jjb-membership-offer",
)


def _method_body(source: str, name: str) -> str:
    start = source.index(f"def {name}")
    rest = source[start:]
    end = rest.find("\n    def ")
    return rest if end == -1 else rest[:end]


class PopupCoverageTests(unittest.TestCase):
    SOURCE = HOME_PAGE.read_text(encoding="utf-8")

    def test_popup_root_covers_all_three(self) -> None:
        """popup_root 与 welcome_popup 都要能定位到三种弹窗。"""
        init = _method_body(self.SOURCE, "__init__")

        for selector in REQUIRED_ROOTS:
            # 用词边界匹配，避免被 .jjb-membership-offer__content 这类
            # 子串蒙混过关（变异验证踩到过）。
            pattern = re.escape(selector) + r"(?![\w-])"
            self.assertRegex(
                init,
                pattern,
                f"popup_root 缺少 {selector}，这类弹窗无法定位、也就无法关闭",
            )

    def test_block_detection_covers_membership_offer(self) -> None:
        """检测不到遮挡，用例只会撞点击超时，看不出真正原因。

        必须用带引号的精确匹配：裸子串 ".jjb-membership-offer" 会被
        ".jjb-membership-offer__content" 满足，摘掉根选择器后测试照样通过
        （写这条守护时的变异验证踩到过）。
        """
        body = _method_body(self.SOURCE, "_popup_blocks_interaction")

        self.assertIn(
            "'.jjb-membership-offer'",
            body,
            "拦截判定漏掉会员 offer 弹窗根节点，CI 上购物车全层会点不动",
        )

    def test_close_controls_cover_membership_offer(self) -> None:
        """会员 offer 的关闭按钮既没有 aria-label 也不叫 modal__close。"""
        body = _method_body(self.SOURCE, "_popup_close_controls")

        self.assertIn(
            ".jjb-membership-offer__close",
            body,
            "漏掉这个关闭按钮会变成'能检测到遮挡但关不掉'",
        )

    def test_popup_not_bypassed_by_style_or_dom_hack(self) -> None:
        """只能点真实关闭控件，不准改样式或删 DOM 绕过弹窗。

        绕过等于把用户真实遇到的遮挡藏起来——线上真有遮挡时用例反而会通过。

        只检查关弹窗相关函数，不扫整个文件：可见性读取
        （style.display !== 'none'）和清理脚本自注入的证据标签
        （oldLabel.remove()）都是合法的，扫全文会误报。
        """
        for name in (
            "_popup_blocks_interaction",
            "_popup_close_controls",
            "close_welcome_popup",
            "close_popup_before_click",
        ):
            if f"def {name}" not in self.SOURCE:
                continue
            body = _method_body(self.SOURCE, name)
            for forbidden in (
                "style.display = 'none'",
                'style.display = "none"',
                "setProperty('display', 'none'",
                "removeChild",
            ):
                self.assertNotIn(
                    forbidden,
                    body,
                    f"{name} 不得用 {forbidden} 绕过弹窗，必须点真实关闭控件",
                )


class PopupOrderTests(unittest.TestCase):
    """三种选择器要放在同一份清单里，避免日后只改一处。"""

    SOURCE = HOME_PAGE.read_text(encoding="utf-8")

    def test_all_roots_appear_in_same_locator_call(self) -> None:
        init = _method_body(self.SOURCE, "__init__")
        # popup_root 的字符串拼接应包含三种 class，允许跨行。
        match = re.search(r"self\.popup_root\s*=\s*page\.locator\((.*?)\)", init, re.S)
        self.assertIsNotNone(match, "未找到 popup_root 的 locator 定义")
        block = match.group(1)

        for selector in REQUIRED_ROOTS:
            # 同样用词边界，避免子串蒙混。
            self.assertRegex(block, re.escape(selector) + r"(?![\w-])")


if __name__ == "__main__":
    unittest.main()
