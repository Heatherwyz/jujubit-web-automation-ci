"""会员模块的接线校验：marker、CASE_TITLES、套件选择口径。

这些都是"漏改一处就静默失效"的地方：
- marker 未在两份 pytest 配置注册 → PytestUnknownMarkWarning，--strict-markers 下直接失败
- CASE_TITLES 漏加 → 报告显示原始函数名
- 默认回归的 marker 表达式漏排除 membership → 默认跑会跑到需登录态的会员用例
"""

from __future__ import annotations

import io
import re
import tokenize
import unittest
from pathlib import Path

from python_playwright.membership_cases import (
    MEMBERSHIP_CASES,
    MEMBERSHIP_CASES_BY_FUNCTION,
    MEMBERSHIP_CASE_TITLES,
)
from python_playwright.tests.conftest import CASE_TITLES

ROOT = Path(__file__).resolve().parents[1]
MEMBERSHIP_TEST_FILE = ROOT / "python_playwright" / "tests" / "test_membership.py"
RUN_ALL = ROOT / "run_all.py"


def _declared_membership_functions() -> set[str]:
    source = MEMBERSHIP_TEST_FILE.read_text(encoding="utf-8")
    return set(re.findall(r"^def (test_\w+)", source, re.MULTILINE))


def strip_comments_and_docstrings(source: str) -> str:
    """只去掉注释与三引号文档字符串，保留普通字符串字面量。

    检查"不该出现某种写法"时必须先剥：这些方法的说明里写着
    "不要按英文 Subscribe to 匹配"这类反面教材，直接扫全文会把说明
    当成违规代码，守护测试变成自己绊自己。

    但不能连普通字符串一起剥——选择器与正则本身就是字符串字面量
    （r"...USD"、get_by_role("tab", ...)），剥掉就无从判断写法是否正确。
    """
    without_docstrings = re.sub(r'""".*?"""|\'\'\'.*?\'\'\'', "", source, flags=re.S)
    kept_lines = []
    for line in without_docstrings.splitlines():
        if line.lstrip().startswith("#"):
            continue
        kept_lines.append(re.sub(r"\s+#\s.*$", "", line))
    return "\n".join(kept_lines)


class CaseMetadataTests(unittest.TestCase):
    def test_cases_were_defined(self) -> None:
        """元数据条数下限：防止有人误删整段而不是单条。

        2026-09-23 从 43 降到 35，分两批：

        - 缺账号状态（5 条）：MEM-06/07/18/21/36，需要 Pro / 已退订 /
          已取消续费 / Premium 用满额度等无法构造的账号；
        - 无法证伪（4 条）：MEM-14/15/39 要真实的 Airwallex 支付失败，
          MEM-42 断言"某事件不出现"——没抓到既可能是真没报，也可能是路径没走到。

        同期新增 MEM-41B（曝光只上报一次），净变化 43 - 9 + 1 = 35。
        下限跟着实际条数走，但不允许再往下掉——否则大段删除不会被发现。
        """
        self.assertGreaterEqual(len(MEMBERSHIP_CASES), 35)

    def test_case_ids_are_unique(self) -> None:
        ids = [case.case_id for case in MEMBERSHIP_CASES]

        self.assertEqual(len(ids), len(set(ids)))

    def test_function_names_are_unique(self) -> None:
        names = [case.function_name for case in MEMBERSHIP_CASES]

        self.assertEqual(len(names), len(set(names)))

    def test_every_declared_test_has_metadata(self) -> None:
        """测试文件里的每个函数都要有元数据，否则报告显示函数名。"""
        declared = _declared_membership_functions()
        missing = sorted(declared - set(MEMBERSHIP_CASES_BY_FUNCTION))

        self.assertEqual(
            missing,
            [],
            "以下会员用例缺少 membership_cases.py 元数据：" + ", ".join(missing),
        )

    def test_no_stale_metadata(self) -> None:
        """元数据里不应有已删除的函数。"""
        declared = _declared_membership_functions()
        stale = sorted(set(MEMBERSHIP_CASES_BY_FUNCTION) - declared)

        self.assertEqual(
            stale,
            [],
            "以下元数据对应的用例已不存在：" + ", ".join(stale),
        )

    def test_titles_carry_case_id(self) -> None:
        """报告标题应带 MEM-xx 编号，便于与手工用例对照。"""
        for case in MEMBERSHIP_CASES:
            self.assertTrue(
                case.report_title.startswith(case.case_id),
                f"{case.function_name} 的标题应以 {case.case_id} 开头",
            )


class CaseTitleWiringTests(unittest.TestCase):
    def test_membership_titles_are_merged_into_case_titles(self) -> None:
        """conftest 的 CASE_TITLES 必须包含全部会员标题。"""
        missing = sorted(set(MEMBERSHIP_CASE_TITLES) - set(CASE_TITLES))

        self.assertEqual(missing, [])

    def test_titles_match_metadata(self) -> None:
        for name, title in MEMBERSHIP_CASE_TITLES.items():
            self.assertEqual(CASE_TITLES[name], title)


class MarkerRegistrationTests(unittest.TestCase):
    """两份 pytest 配置都要注册 membership 与 membership_session。"""

    REQUIRED = ("membership", "membership_session")

    def test_ini_registers_markers(self) -> None:
        text = (ROOT / "pytest-playwright.ini").read_text(encoding="utf-8")
        for marker in self.REQUIRED:
            # 需要 MULTILINE：marker 是缩进的续行，不在字符串开头。
            self.assertTrue(
                re.search(rf"^\s+{marker}:", text, re.MULTILINE),
                f"pytest-playwright.ini 缺 {marker}",
            )

    def test_pyproject_registers_markers(self) -> None:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        for marker in self.REQUIRED:
            self.assertIn(f'"{marker}:', text, f"pyproject.toml 缺 {marker}")

    def test_module_level_marker_applied(self) -> None:
        """整个会员模块打 membership marker，run_all 才能用 -m 选中。"""
        source = MEMBERSHIP_TEST_FILE.read_text(encoding="utf-8")

        self.assertIn("pytestmark = pytest.mark.membership", source)

    def test_contract_file_also_marked(self) -> None:
        contract = (
            ROOT / "python_playwright" / "tests" / "test_membership_html_contract.py"
        ).read_text(encoding="utf-8")

        self.assertIn("pytest.mark.membership", contract)


class DefaultSuiteScopeTests(unittest.TestCase):
    """默认回归不能跑会员模块：会员用例需登录态，且支付要拉起第三方表单。"""

    def test_default_marker_excludes_membership(self) -> None:
        from run_all import DEFAULT_MARKER_EXPRESSION

        self.assertIn("not membership", DEFAULT_MARKER_EXPRESSION)
        self.assertIn("not cart_session", DEFAULT_MARKER_EXPRESSION)

    def test_run_all_exposes_membership_flags(self) -> None:
        text = RUN_ALL.read_text(encoding="utf-8")

        self.assertIn("--membership", text)
        self.assertIn("--membership-only", text)

    def test_membership_only_rejects_cart_flags(self) -> None:
        """两个套件的登录态与副作用不同，不应混跑。"""
        text = RUN_ALL.read_text(encoding="utf-8")

        self.assertIn("--membership-only 不能与任何购物车参数同时使用", text)


class StorageStateWiringTests(unittest.TestCase):
    """membership_session 必须加载 storage-state；流水线必须把 Secret 写进文件。

    历史上会员用例只打了 marker，page fixture 仍建匿名 Context，点 Get 会跳
    Shopify 登录页，整组支付/管理页都变成未完成。每日全量工作流也漏了还原
    PLAYWRIGHT_STORAGE_STATE_JSON，购物车层同样拿不到登录态。
    """

    def test_page_fixture_loads_storage_for_membership_session(self) -> None:
        source = (
            ROOT / "python_playwright" / "tests" / "conftest.py"
        ).read_text(encoding="utf-8")

        self.assertIn("is_membership_session", source)
        self.assertIn(
            "needs_storage = is_cart_session or is_membership_session",
            source,
        )
        self.assertIn('options["storage_state"] = str(storage_state)', source)

    def test_daily_regression_restores_storage_secret(self) -> None:
        text = (ROOT / ".github" / "workflows" / "daily-regression.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("PLAYWRIGHT_STORAGE_STATE_JSON", text)
        self.assertIn("artifacts/auth/storage-state.json", text)
        self.assertLess(
            text.index("准备登录状态"),
            text.index("执行会员 UI 回归"),
        )
        self.assertLess(
            text.index("准备登录状态"),
            text.index("执行购物车 UI 回归"),
        )

    def test_membership_workflow_restores_storage_secret(self) -> None:
        text = (
            ROOT / ".github" / "workflows" / "membership-ui-tests.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("PLAYWRIGHT_STORAGE_STATE_JSON", text)
        self.assertIn("artifacts/auth/storage-state.json", text)
        self.assertLess(
            text.index("准备登录状态"),
            text.index("执行会员 UI 回归"),
        )


class StorageStateExportTests(unittest.TestCase):
    """导出脚本的登录判定分两层，不能只看 URL。"""

    def test_login_and_code_pages_are_not_done(self) -> None:
        """还停在登录页或验证码页时，这一跳没走完。"""
        from scripts.export_storage_state import is_logged_in_url

        self.assertFalse(
            is_logged_in_url(
                "https://shopify.com/authentication/95408849267/login"
            )
        )
        self.assertFalse(
            is_logged_in_url(
                "https://shopify.com/authentication/95408849267/code?_y=x"
            )
        )

    def test_leaving_login_page_is_only_a_coarse_filter(self) -> None:
        """回到店内页面只说明跳转结束，不代表店面已登录。

        真正的判定是 storefront_signed_in 读会员页 overview——实测过一次
        Shopify 托管账户页能打开、订单都能看，但会员页仍显示
        "Log in to view your plan"。
        """
        from scripts.export_storage_state import is_logged_in_url

        self.assertTrue(is_logged_in_url("https://jujubit.ai/account"))
        self.assertTrue(
            is_logged_in_url("https://shopify.com/95408849267/account/orders")
        )
        self.assertTrue(
            is_logged_in_url(
                "https://jujubit.ai/pages/vip-program?entry_page=header"
            )
        )

    def test_storefront_session_requires_jujubit_essential(self) -> None:
        """判定店面登录态只认 jujubit.ai 域的 _shopify_essential。

        实测过：只有 shopify.com 域的凭据时，Shopify 托管账户页能打开、订单
        都能看，但会员页 overview 仍显示 "Log in to view your plan"，
        membership_session 用例照样拿不到会员数据。
        """
        from scripts.import_iab_storage_state import has_storefront_session

        shopify_only = [
            {"name": "_shopify_essential", "domain": "shopify.com"},
            {"name": "_shopify_essential", "domain": ".shopify.com"},
        ]
        self.assertFalse(has_storefront_session(shopify_only))

        with_storefront = shopify_only + [
            {"name": "_shopify_essential", "domain": "jujubit.ai"}
        ]
        self.assertTrue(has_storefront_session(with_storefront))

        analytics_only = [
            {"name": "_shopify_analytics", "domain": "jujubit.ai"},
            {"name": "_shopify_marketing", "domain": "jujubit.ai"},
        ]
        self.assertFalse(has_storefront_session(analytics_only))

    def test_chrome_timestamp_conversion(self) -> None:
        """Chrome 的 expires_utc 是 1601 纪元微秒，不转换会全部判成已过期。"""
        from scripts.import_iab_storage_state import chrome_us_to_unix

        # 0 表示会话 Cookie，storage-state 用 -1 表达。
        self.assertEqual(chrome_us_to_unix(0), -1)
        # 13465901800631592 微秒 ≈ 2027-08 前后，必须是正的未来时间戳。
        converted = chrome_us_to_unix(13_465_901_800_631_592)
        self.assertGreater(converted, 1_700_000_000)
        self.assertLess(converted, 2_000_000_000)

    def test_import_script_does_not_leak_cookie_values(self) -> None:
        """日志只打名字与数量；Cookie 值不能进终端或 CI 日志。"""
        source = (ROOT / "scripts" / "import_iab_storage_state.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("print(c['value']", source)
        self.assertNotIn('print(cookie["value"]', source)
        self.assertIn("不打印 Cookie 值", source)

    def test_export_uses_storefront_login_entry(self) -> None:
        """必须走 /customer_authentication/login。

        /account/login 用的 client_id 回调到 shopify.com/.../account/callback，
        只给 Shopify 托管账户页种会话，jujubit.ai 店面仍显示
        "Log in to view your plan"，membership_session 用例照样拿不到会员数据。
        """
        source = (ROOT / "scripts" / "export_storage_state.py").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "https://jujubit.ai/customer_authentication/login", source
        )
        self.assertIn("storefront_signed_in", source)
        self.assertIn("log in to view your plan", source.lower())


class PaymentAssertionTrapTests(unittest.TestCase):
    """2026-09-20 实跑踩到的三个断言陷阱，改回去就会静默失效。

    这些都是"单独手工验证能过、用例必败"或"恒真恒假"的写法，
    光看代码看不出问题，所以在离线层钉住。
    """

    PAGE_SOURCE = (
        ROOT / "python_playwright" / "pages" / "membership_page.py"
    ).read_text(encoding="utf-8")

    def test_payment_container_uses_visibility_not_count(self) -> None:
        """.jjb-membership-checkout 常驻 DOM，count() 判定恒真。

        未拉起支付时它就存在（隐藏态），且 __plan / __price 预置了
        'Pro Membership'、'$19.90' 模板文案。用 count() 会立刻误判成
        "半屏已出现"，既读到与当前档位无关的假数据，也永远走不到
        整页跳转 Airwallex 的分支。
        """
        self.assertIn("def _visible_text", self.PAGE_SOURCE)
        self.assertIn("is_visible()", self.PAGE_SOURCE)
        self.assertIn("payment_layer_visible", self.PAGE_SOURCE)
        # 读取套餐/金额/账期必须走可见性封装，不能直接 count() 取文案。
        for helper in (
            "payment_plan_label",
            "payment_billing_label",
            "payment_amount_text",
        ):
            code = self._method_code(helper)
            self.assertIn(
                "_visible_text",
                code,
                f"{helper} 必须用 _visible_text 读站内节点，否则会读到隐藏模板文案",
            )

    def test_hosted_page_assertions_are_locale_agnostic(self) -> None:
        """Airwallex 托管页按 locale 渲染，只匹配英文会在 CI 恒空。

        CI 的 Chromium 显示中文（"订阅 …"、"每月 预付结算"），
        手工打开常是英文（"Subscribe to …"、"Billed monthly"）。
        """
        plan_code = self._method_code("payment_plan_label")
        self.assertNotIn(
            "Subscribe to",
            plan_code,
            "套餐名不能按英文 'Subscribe to' 匹配——CI 渲染中文时恒空",
        )
        self.assertIn("Membership", plan_code)

        billing_code = self._method_code("payment_billing_label")
        self.assertIn("每", billing_code, "账期断言要同时认中文写法")

    def test_amount_anchors_on_usd_not_trailing_label(self) -> None:
        """今日应付金额锚 USD，不能按标签往后捕获。

        中文把标签放在金额后面（"$191.04 USD 今日应付金额"），
        按标签往后捕获会抓到下一行的小计原价 $238.80，
        把已生效的首年 8 折误判成没打折。
        """
        code = self._method_code("payment_amount_text")

        self.assertIn("USD", code)
        self.assertNotIn(
            "Total due today[^$]*",
            code,
            "不能按标签往后捕获金额——中文标签在金额之后，会抓到小计原价",
        )

    def test_reload_specifies_wait_until(self) -> None:
        """page.reload() 默认等 load 事件，首页第三方资源多会 30 秒超时。

        MEM-37/38 曾因此整条失败，看起来像弹窗问题，实际是导航等待策略。
        """
        code = strip_comments_and_docstrings(
            MEMBERSHIP_TEST_FILE.read_text(encoding="utf-8")
        )

        self.assertNotIn(
            "page.reload()",
            code,
            "reload 必须指定 wait_until，否则等 load 事件会超时",
        )

    def test_monthly_cycle_assertion_accepts_chinese(self) -> None:
        """MEM-11 的月付断言要认中文"每月"。"""
        source = MEMBERSHIP_TEST_FILE.read_text(encoding="utf-8")

        self.assertIn("每月", source)
        self.assertNotIn(
            '"month" in (label + billing).lower()',
            source,
            "只匹配 'month' 会在 CI 渲染中文时恒假",
        )

    def _method_body(self, name: str) -> str:
        """截取指定方法的源码片段，用于检查写法。"""
        marker = f"    def {name}("
        start = self.PAGE_SOURCE.index(marker)
        rest = self.PAGE_SOURCE[start + len(marker) :]
        end = rest.find("\n    def ")
        return rest if end == -1 else rest[:end]

    def _method_code(self, name: str) -> str:
        """只保留可执行代码，剥掉注释与文档字符串。

        必须剥：这些方法的说明里会写"不要按英文 Subscribe to 匹配"之类的
        反面教材，直接扫全文会把说明文字当成违规代码。
        """
        return strip_comments_and_docstrings(self._method_body(name))


class MembershipAdminPageTests(unittest.TestCase):
    """管理页入口与页签定位，两处都曾指向错误位置。"""

    def test_admin_cases_do_not_goto_account(self) -> None:
        """/account 会 302 到 Shopify 托管页，那里没有 MEMBERSHIP 页签。"""
        source = MEMBERSHIP_TEST_FILE.read_text(encoding="utf-8")

        self.assertNotIn(
            'page.goto(f"{home.base_url}/account"',
            source,
            "管理页用例应走会员页的 MEMBERSHIP 视图，不是 /account",
        )
        self.assertIn("def _open_membership", source)

    def test_membership_tab_is_role_tab_not_href(self) -> None:
        """页签是 role=tab 按钮；a[href*=membership] 实测 0 命中，恒假。"""
        source = (
            ROOT / "python_playwright" / "pages" / "membership_page.py"
        ).read_text(encoding="utf-8")
        # 剥注释：说明文字里写着"不是 a[href*=membership]"，会被误判。
        code = strip_comments_and_docstrings(source)

        self.assertNotIn('a[href*="membership"]', code)
        self.assertIn('get_by_role("tab", name="Membership")', code)

    def test_profile_tab_order_matches_membership_page(self) -> None:
        """会员页只有 MEMBERSHIP / PLANS，Profile/Orders 在 Shopify 托管页。"""
        from python_playwright.pages.membership_page import PROFILE_TAB_ORDER

        self.assertEqual(PROFILE_TAB_ORDER, ("MEMBERSHIP", "PLANS"))

    def test_offer_popup_close_can_wait_for_render(self) -> None:
        """offer 弹窗约 9 秒后才渲染，不等就检查不到它。

        不等的后果是点击时它才出现并拦住事件，报
        "__content intercepts pointer events" 的 click timeout。
        """
        source = (
            ROOT / "python_playwright" / "pages" / "membership_page.py"
        ).read_text(encoding="utf-8")

        self.assertIn("TIMEOUT_OFFER_RENDER", source)
        self.assertIn("observe_timeout", source)
        # 三个点击入口都要先关弹窗。
        for entry in ("def click_get", "def switch_cycle", "def open_membership_tab"):
            start = source.index(entry)
            body = source[start : start + 1200]
            self.assertIn(
                "close_membership_popup",
                body,
                f"{entry} 点击前必须关 offer 弹窗",
            )

    def test_click_entries_also_close_newsletter_popup(self) -> None:
        """newsletter 弹窗和会员 offer 是两层不同遮罩，都要关。

        MEM-02 是匿名用例，挡住它的是 .newsletter-popup-v2 的图片，
        只关会员 offer 仍会报 __image intercepts pointer events。
        """
        source = (
            ROOT / "python_playwright" / "pages" / "membership_page.py"
        ).read_text(encoding="utf-8")

        for entry in ("def click_get", "def switch_cycle"):
            start = source.index(entry)
            body = source[start : start + 1200]
            self.assertIn(
                "close_popup_before_click",
                body,
                f"{entry} 还要关 newsletter 弹窗，匿名用例会被它拦住",
            )


class PaymentBoundaryTests(unittest.TestCase):
    """支付用例必须停在"拉起表单"，不能真的付款。"""

    def test_no_pay_now_click_in_tests(self) -> None:
        source = MEMBERSHIP_TEST_FILE.read_text(encoding="utf-8")
        lowered = source.lower()

        # 不应出现点击 Pay Now / 提交支付的动作
        for forbidden in ("pay_now", "click_pay", "submit_payment"):
            self.assertNotIn(
                forbidden,
                lowered,
                f"会员用例不应包含 {forbidden}——支付只走到表单可见",
            )

    def test_payment_boundary_documented(self) -> None:
        source = MEMBERSHIP_TEST_FILE.read_text(encoding="utf-8")

        self.assertIn("不填卡", source)
        self.assertIn("不点 Pay Now", source)

    def test_page_object_has_no_card_filling(self) -> None:
        """页面对象不应提供填卡方法，避免误用产生真实扣款。"""
        page_source = (
            ROOT / "python_playwright" / "pages" / "membership_page.py"
        ).read_text(encoding="utf-8")

        for forbidden in ("def fill_card", "def submit_payment", "def pay_now"):
            self.assertNotIn(forbidden, page_source)

    def test_no_hardcoded_card_number_in_code(self) -> None:
        """测试卡号只应出现在文档里，不写进代码。"""
        for path in (
            MEMBERSHIP_TEST_FILE,
            ROOT / "python_playwright" / "pages" / "membership_page.py",
        ):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("4035", text, f"{path.name} 不应硬编码测试卡号")


class LoginStateVerdictTests(unittest.TestCase):
    """登录态失效必须报"未完成"，不能报成"支付未拉起"的业务失败。

    历史问题（2026-09-22 本地全量）：登录态过期后整页跳到
    shopify.com/authentication/.../oauth/authorize，等待循环耗完 SDK 超时才抛
    AssertionError，6 条支付用例被判业务失败；同一根因的另外 15 条会员用例却
    正确报了"缺少有效登录态"。同一个环境问题只能有一种口径，否则看报告的人会
    去查支付功能，而真正要做的是重新导出登录态。
    """

    PAGE_OBJECT = ROOT / "python_playwright" / "pages" / "membership_page.py"

    def test_wait_loop_aborts_on_login_redirect(self) -> None:
        """等待支付表单时必须先识别登录页，不能等到超时。

        必须先剥注释与文档字符串：这段实现的注释里就写着"误报成『支付未拉起』"
        这样的反面说明，直接扫原文会把说明当成代码顺序，守护测试自己绊自己。
        """
        source = strip_comments_and_docstrings(
            self.PAGE_OBJECT.read_text(encoding="utf-8")
        )
        start = source.index("def wait_for_payment_form")
        body = source[start : source.index("def _wait_for_hosted_payment_ready")]

        self.assertIn(
            "on_customer_login_page",
            body,
            "wait_for_payment_form 必须在跳登录页时立刻中止，否则超时会误报支付失败",
        )
        self.assertLess(
            body.index("on_customer_login_page"),
            body.index("支付未拉起"),
            "登录页判断必须早于『支付未拉起』的 AssertionError",
        )

    def test_login_redirect_raises_dedicated_error(self) -> None:
        """登录态失效用专用异常，不能复用 AssertionError。"""
        source = self.PAGE_OBJECT.read_text(encoding="utf-8")

        self.assertIn("class MembershipLoginRequiredError", source)
        start = source.index("def wait_for_payment_form")
        body = source[start : source.index("def _wait_for_hosted_payment_ready")]
        self.assertIn("raise MembershipLoginRequiredError", body)

    def test_payment_tests_skip_instead_of_fail(self) -> None:
        """三条支付用例都要走会 skip 的包装，不能直接调等待方法。"""
        source = MEMBERSHIP_TEST_FILE.read_text(encoding="utf-8")
        cleaned = strip_comments_and_docstrings(source)

        self.assertIn("except MembershipLoginRequiredError", cleaned)
        self.assertIn("pytest.skip", cleaned)
        for name in (
            "def test_mem11_pro_monthly_payment_form",
            "def test_mem12_pro_yearly_payment_form",
            "def test_mem13_premium_monthly_payment_form",
        ):
            start = cleaned.index(name)
            body = cleaned[start : start + 1400]
            self.assertIn(
                "_wait_for_payment_or_skip",
                body,
                f"{name} 应走 _wait_for_payment_or_skip，登录态失效才会记为未完成",
            )
            self.assertNotIn(
                "mp.wait_for_payment_form()",
                body,
                f"{name} 不应直接调 wait_for_payment_form，登录态失效会被误判成业务失败",
            )


if __name__ == "__main__":
    unittest.main()
