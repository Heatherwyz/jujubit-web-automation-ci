"""登录态失效的两种形态都要判成"未完成"，不能误报业务失败。

2026-09-23 实测踩到：MEM-11/12/13 三条支付用例同时报"支付未拉起"的业务失败，
诊断信息是 rootVisible=False、mountChildren=2。查下来根因是 Shopify 会话过期，
但站点的表现不是跳登录页——而是跳 ?plan=PRO&billingCycle=... 再**跳回会员页**。

原检测只认 on_customer_login_page（URL 含 /authentication/ 或 /login），
这种"跳回原地"的形态压根不进登录页，于是漏判：耗完 45 秒 SDK 超时后，
把"本轮没有登录态、什么也没验证"报成了"支付功能坏了"。

两者口径完全不同：业务失败要立刻查站点，未完成只需重新导出登录态。
"""

from __future__ import annotations

import unittest

from python_playwright.pages.membership_page import (
    SEL_OVERVIEW_SIGNED_OUT,
    MembershipPage,
)


class _Page:
    """只实现 storefront_signed_out() 需要的 evaluate。"""

    def __init__(self, *, result=None, raises: Exception | None = None):
        self._result = result
        self._raises = raises
        self.calls: list[str] = []

    def evaluate(self, script, arg=None):
        self.calls.append(str(arg))
        if self._raises is not None:
            raise self._raises
        return self._result


def _signed_out(result=None, raises: Exception | None = None) -> bool:
    page = _Page(result=result, raises=raises)
    mp = MembershipPage.__new__(MembershipPage)
    mp.page = page
    return MembershipPage.storefront_signed_out(mp)


class StorefrontSignedOutTests(unittest.TestCase):
    def test_signed_out_when_overview_asks_to_log_in(self) -> None:
        """页面脚本判定未登录时返回 True。"""
        self.assertTrue(_signed_out(True))

    def test_signed_in_when_overview_shows_account(self) -> None:
        self.assertFalse(_signed_out(False))

    def test_navigation_error_is_not_treated_as_signed_out(self) -> None:
        """跳转途中读不到 DOM 不能当成未登录，否则会把正常跳转判成失效。"""
        from playwright.sync_api import Error as PlaywrightError

        self.assertFalse(
            _signed_out(raises=PlaywrightError("Execution context was destroyed"))
        )

    def test_passes_signed_out_selector_to_page(self) -> None:
        """显式的 __signed-out 容器仍是首选判据。"""
        page = _Page(result=True)
        mp = MembershipPage.__new__(MembershipPage)
        mp.page = page
        MembershipPage.storefront_signed_out(mp)

        self.assertIn(SEL_OVERVIEW_SIGNED_OUT, page.calls[0])


class PaymentWaitReportsUnfinishedTests(unittest.TestCase):
    """wait_for_payment_form 必须在两种形态下都抛 MembershipLoginRequiredError。"""

    SOURCE = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "python_playwright"
        / "pages"
        / "membership_page.py"
    ).read_text(encoding="utf-8")

    def test_wait_loop_checks_both_expiry_shapes(self) -> None:
        body_start = self.SOURCE.index("def wait_for_payment_form")
        body = self.SOURCE[body_start : body_start + 4000]

        self.assertIn("on_customer_login_page", body)
        self.assertIn(
            "storefront_signed_out",
            body,
            "跳回会员页的失效形态也要检测，否则误报成业务失败",
        )
        self.assertEqual(
            body.count("MembershipLoginRequiredError"),
            2,
            "两种形态各自抛一次，缺一种就会漏判",
        )

    def test_tests_skip_on_login_required(self) -> None:
        """用例侧必须把这个异常转成 skip（未完成），不是让它冒泡成失败。"""
        tests = (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "python_playwright"
            / "tests"
            / "test_membership.py"
        ).read_text(encoding="utf-8")

        self.assertIn("except MembershipLoginRequiredError", tests)
        self.assertIn("pytest.skip", tests)


if __name__ == "__main__":
    unittest.main()
