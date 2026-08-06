"""首页页面对象。

把访问首页、关闭优惠弹窗、打开导航等重复操作集中在这里，测试用例只保留
业务断言，定位器变化时也只需要修改这一处。
"""

import time
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, expect


class HomePage:
    """JuJuBit 首页的可复用操作集合。"""

    def __init__(self, page: Page, base_url: str, config):
        self.page = page
        self.base_url = base_url.rstrip("/")
        self.config = config
        self.announcement = page.get_by_role("region", name="Announcement bar")
        self.primary_nav = page.get_by_role("navigation", name="Primary")
        # 线上主题曾同时出现新旧两种优惠弹窗 class，统一覆盖，避免遮挡点击。
        self.welcome_popup = page.locator(
            ".newsletter-popup-v2:visible, .newsletter-popup--original:visible"
        )

    def open(self) -> None:
        """打开首页，并在站点返回 429 时限速等待后重试。

        HTTP 429 是站点对高频访问的频控信号，不是首页功能断言失败。默认模式
        会自动退避重试；带 ``--pw-manual-verification`` 时会显示浏览器，允许
        使用者手动完成网站要求的验证后再继续，脚本不会自动绕过验证。
        """
        retries = max(0, self.config.getoption("--pw-429-retries"))
        manual_verification = self.config.getoption("--pw-manual-verification")
        # 人工模式在首次 429 时立即交给使用者确认；普通模式才按退避策略重试。
        total_attempts = 2 if manual_verification else retries + 1
        for attempt in range(total_attempts):
            self._pace_site_request()
            response = self.page.goto(self.base_url, wait_until="commit")
            if response is not None and response.status == 429:
                if manual_verification and attempt == 0:
                    self._wait_for_manual_verification()
                    continue
                if not manual_verification and attempt < retries:
                    # 递增退避比立即重试更容易让站点解除频控，也避免继续放大请求量。
                    delay = min(15 * (2**attempt), 60)
                    print(f"首页触发 HTTP 429，等待 {delay} 秒后第 {attempt + 1} 次重试。")
                    time.sleep(delay)
                    continue
                raise AssertionError(
                    "首页访问被站点频控拦截：HTTP 429。"
                    "这不是页面功能缺陷；请稍后重试，或用 "
                    "`.venv/bin/python run_all.py --manual-verification` "
                    "在可见浏览器中手动完成网站要求的验证后继续。"
                )
            if response is not None and not response.ok:
                raise AssertionError(f"首页请求失败：HTTP {response.status}，{response.url}")
            try:
                self.page.locator("main").wait_for(state="visible", timeout=15_000)
                self.page.wait_for_function("document.readyState !== 'loading'", timeout=30_000)
                return
            except PlaywrightTimeoutError:
                # 只有最后一次仍未渲染主内容才抛错；429 的额外重试同样适用。
                if attempt == total_attempts - 1:
                    raise

    def _pace_site_request(self) -> None:
        """在不同用例之间保留间隔，降低连续打开首页被限流的概率。"""
        pacer = getattr(self.config, "_jujubit_site_pacer", None)
        if pacer is not None:
            pacer.wait()

    def pace_link_check_request(self) -> None:
        """在批量站内链接检查前限速，避免扫描本身触发站点 429。"""
        pacer = getattr(self.config, "_jujubit_link_pacer", None)
        if pacer is not None:
            pacer.wait()

    def _wait_for_manual_verification(self) -> None:
        """暂停 pytest，等待使用者在可见浏览器中自主完成网站验证。"""
        prompt = (
            "\n首页收到 HTTP 429。请在已打开的浏览器中完成网站要求的确认/验证，"
            "确认首页内容已经显示后按 Enter 继续测试："
        )
        try:
            input(prompt)
        except EOFError as error:
            raise AssertionError(
                "当前终端无法接收人工确认；请在本机终端使用 "
                "`run_all.py --manual-verification` 重新执行。"
            ) from error

    def close_welcome_popup(self) -> bool:
        """若优惠弹窗出现则关闭，返回本次是否实际关闭了弹窗。"""
        # 弹窗为异步出现：等待短时间，出现后关闭；未出现则继续测试。
        try:
            self.welcome_popup.wait_for(state="visible", timeout=4_000)
        except PlaywrightTimeoutError:
            return False
        close_button = self.welcome_popup.get_by_role("button", name="Close", exact=True)
        # 页面脚本偶发晚于弹窗渲染完成，首次点击未生效时只重试一次，避免后续操作被遮挡。
        for attempt in range(2):
            close_button.click()
            try:
                self.welcome_popup.wait_for(state="hidden", timeout=3_000)
                return True
            except PlaywrightTimeoutError:
                if attempt == 1:
                    raise AssertionError("优惠弹窗连续点击两次后仍未关闭")
                self.page.wait_for_timeout(500)
        return False

    def visible_logo(self):
        """返回当前视口中指向首页的品牌 Logo。"""
        return self.page.locator('a[aria-label="JuJuBit"][href="/"]:visible')

    def navigation_root(self, platform: str):
        """返回当前端可见的一级导航；H5 会先真实打开导航抽屉。"""
        if platform == "pc":
            expect(self.primary_nav).to_be_visible()
            return self.primary_nav
        # H5 导航不能只检查隐藏 DOM，必须真实点击菜单按钮并确认抽屉已展示。
        menu_button = self.page.get_by_role("button", name="Site navigation", exact=True)
        expect(menu_button).to_have_count(1)
        drawer_navigation = self.page.locator("#NavDrawer .jjb-mobile-nav")
        # 首屏脚本可能晚于按钮出现；只在抽屉仍隐藏时重试一次，避免重复点击导致抽屉再次收起。
        for attempt in range(2):
            if drawer_navigation.is_visible():
                return drawer_navigation
            self.close_welcome_popup()
            menu_button.click()
            try:
                expect(drawer_navigation).to_be_visible(timeout=3_000)
                return drawer_navigation
            except AssertionError:
                if attempt == 1:
                    raise
                self.page.wait_for_timeout(400)
        return drawer_navigation

    def assert_internal_links(self, root) -> None:
        """断言给定导航区域内的链接均为有效站内链接。"""
        # 校验页面实际渲染的 href，不预设 /pages/create 等历史固定路径。
        hrefs = root.locator("a[href]").evaluate_all("nodes => nodes.map(node => node.getAttribute('href'))")
        assert hrefs, "导航中至少应有一个真实链接"
        expected_host = urlparse(self.base_url).netloc
        for href in hrefs:
            assert href and href.strip() != "#", f"导航存在空链接：{href!r}"
            resolved = urljoin(f"{self.base_url}/", href)
            assert urlparse(resolved).netloc == expected_host, f"导航出现非本站链接：{href}"
