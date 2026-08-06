"""首页页面对象。

把访问首页、关闭优惠弹窗、打开导航等重复操作集中在这里，测试用例只保留
业务断言，定位器变化时也只需要修改这一处。
"""

import time
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, expect


class HomePage:
    """JuJuBit 首页的可复用操作集合。"""

    def __init__(self, page: Page, base_url: str, config):
        self.page = page
        self.base_url = base_url.rstrip("/")
        self.config = config
        self._popup_checked_url = ""
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
            # 显式重新打开页面后需要重新观察异步弹窗出现窗口。
            self._popup_checked_url = ""
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
        # 同一地址第一次最多观察 7 秒，覆盖线上延迟弹窗；后续调用只做快速复查。
        current_url = self.page.url
        wait_timeout = 7_000 if self._popup_checked_url != current_url else 500
        try:
            self.welcome_popup.wait_for(state="visible", timeout=wait_timeout)
        except PlaywrightTimeoutError:
            self._popup_checked_url = current_url
            return False
        close_button = self.welcome_popup.get_by_role("button", name="Close", exact=True)
        # 页面脚本偶发晚于弹窗渲染完成，首次点击未生效时只重试一次，避免后续操作被遮挡。
        for attempt in range(2):
            close_button.click()
            try:
                self.welcome_popup.wait_for(state="hidden", timeout=3_000)
                self._popup_checked_url = current_url
                return True
            except PlaywrightTimeoutError:
                if attempt == 1:
                    raise AssertionError("优惠弹窗连续点击两次后仍未关闭")
                self.page.wait_for_timeout(500)
        return False

    def visible_logo(self):
        """返回当前视口中指向首页的品牌 Logo。"""
        return self.page.locator('a[aria-label="JuJuBit"][href="/"]:visible')

    def wait_for_theme_interactions(self) -> None:
        """等待 Shopify 主题完成导航与 Footer 交互组件初始化。"""
        self.page.wait_for_function(
            """() => Boolean(
                window.theme?.NavDrawer
                && window.theme?.sections?.instances?.some(item => item?.type === 'footer')
            )""",
            timeout=20_000,
        )

    def navigation_root(self, platform: str):
        """返回当前端可见的一级导航；H5 会先真实打开导航抽屉。"""
        if platform == "pc":
            expect(self.primary_nav).to_be_visible()
            return self.primary_nav
        # H5 导航不能只检查隐藏 DOM，必须真实点击菜单按钮并确认抽屉已展示。
        menu_button = self.page.get_by_role("button", name="Site navigation", exact=True)
        expect(menu_button).to_have_count(1)
        drawer_navigation = self.page.locator("#NavDrawer .jjb-mobile-nav")
        # GitHub Runner 上按钮 DOM 会早于主题交互脚本出现；必须等初始化完成后再点击。
        # 若当前页面初始化失败，重新打开一次首页再试，避免把环境抖动当成产品缺陷。
        for attempt in range(2):
            if drawer_navigation.is_visible():
                return drawer_navigation
            self.close_welcome_popup()
            try:
                self.wait_for_theme_interactions()
                menu_button.click()
                self.page.wait_for_function(
                    """() => {
                        const button = document.querySelector(
                            'button[aria-controls="NavDrawer"][aria-label="Site navigation"]'
                        );
                        const drawer = document.getElementById('NavDrawer');
                        return button?.getAttribute('aria-expanded') === 'true'
                            && drawer?.classList.contains('drawer--is-open');
                    }""",
                    timeout=10_000,
                )
                expect(drawer_navigation).to_be_visible(timeout=5_000)
                return drawer_navigation
            except (AssertionError, PlaywrightTimeoutError):
                if attempt == 1:
                    raise AssertionError("H5 菜单按钮点击后导航抽屉未展开")
                self.open()
        return drawer_navigation

    def mark_failure_evidence(self, locator: Locator, note: str) -> dict:
        """把问题元素滚动到视口、加红框，并保存报告所需的 DOM 路径。"""
        try:
            # 失败截图同样不能被稍后出现的优惠弹窗遮挡。
            self.close_welcome_popup()
            target = locator.first
            target.scroll_into_view_if_needed()
            self.page.wait_for_timeout(300)
            return target.evaluate(
                """(element, note) => {
                    const cssPath = (target) => {
                        const parts = [];
                        let current = target;
                        while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 7) {
                            let part = current.tagName.toLowerCase();
                            if (current.id) {
                                part += `#${CSS.escape(current.id)}`;
                                parts.unshift(part);
                                break;
                            }
                            const classes = [...current.classList]
                                .filter(name => !name.startsWith('is-'))
                                .slice(0, 2);
                            if (classes.length) {
                                part += `.${classes.map(name => CSS.escape(name)).join('.')}`;
                            }
                            const siblings = current.parentElement
                                ? [...current.parentElement.children]
                                    .filter(item => item.tagName === current.tagName)
                                : [];
                            if (siblings.length > 1) {
                                part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
                            }
                            parts.unshift(part);
                            if (['MAIN', 'HEADER', 'FOOTER', 'NAV'].includes(current.tagName)) break;
                            current = current.parentElement;
                        }
                        return parts.join(' > ');
                    };

                    const oldLabel = document.getElementById('jujubit-test-evidence-label');
                    if (oldLabel) oldLabel.remove();
                    element.style.setProperty('outline', '5px solid #ff2d2d', 'important');
                    element.style.setProperty('outline-offset', '4px', 'important');
                    element.style.setProperty('background-color', 'rgba(255, 45, 45, 0.16)', 'important');

                    const rect = element.getBoundingClientRect();
                    const label = document.createElement('div');
                    label.id = 'jujubit-test-evidence-label';
                    label.textContent = '错误位置';
                    Object.assign(label.style, {
                        position: 'fixed',
                        zIndex: '2147483646',
                        left: `${Math.max(8, Math.min(rect.left, window.innerWidth - 96))}px`,
                        top: `${Math.max(8, rect.top - 34)}px`,
                        padding: '5px 9px',
                        background: '#ff2d2d',
                        color: '#fff',
                        borderRadius: '4px',
                        font: 'bold 13px/1.2 Arial, sans-serif',
                        pointerEvents: 'none',
                    });
                    document.body.appendChild(label);

                    const evidence = {
                        note,
                        selector: cssPath(element),
                        tag: element.tagName.toLowerCase(),
                        text: (element.innerText || element.getAttribute('aria-label') || '')
                            .trim().replace(/\\s+/g, ' ').slice(0, 240),
                        attributes: {
                            href: element.getAttribute('href'),
                            loading: element.getAttribute('loading'),
                            rel: element.getAttribute('rel'),
                            ariaLabel: element.getAttribute('aria-label'),
                        },
                        box: {
                            x: Math.round(rect.left + window.scrollX),
                            y: Math.round(rect.top + window.scrollY),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                        },
                    };
                    window.__jujubitTestEvidence = evidence;
                    return evidence;
                }""",
                note,
            )
        except Exception:
            # 证据标记失败不能覆盖原始业务断言；报告仍会记录页面 URL 和当前视口截图。
            return {}

    def assert_internal_links(self, root) -> None:
        """断言给定导航区域内的链接均为有效站内链接。"""
        # H5 语言选项是 JS 操作控件（href="#"），不属于站内页面导航，由语言切换 case 覆盖。
        links = root.locator('a[href]:not([data-jjb-mobile-locale-option])')
        items = links.evaluate_all(
            """nodes => nodes.map(node => ({
                href: node.getAttribute('href'),
                text: (node.innerText || node.getAttribute('aria-label') || '')
                    .trim().replace(/\\s+/g, ' '),
            }))"""
        )
        assert items, "导航中至少应有一个真实链接"
        expected_host = urlparse(self.base_url).netloc
        for index, item in enumerate(items):
            href = item["href"]
            if not href or href.strip() == "#":
                evidence = self.mark_failure_evidence(
                    links.nth(index),
                    f"导航项 {item['text']!r} 的 href={href!r}",
                )
                raise AssertionError(
                    "导航链接无效："
                    f"页面={self.page.url}；文案={item['text']!r}；href={href!r}；"
                    f"元素路径={evidence.get('selector', '未捕获')}"
                )
            resolved = urljoin(f"{self.base_url}/", href)
            if urlparse(resolved).netloc != expected_host:
                evidence = self.mark_failure_evidence(
                    links.nth(index),
                    f"导航项 {item['text']!r} 跳到非本站地址 {resolved}",
                )
                raise AssertionError(
                    "导航出现非本站链接："
                    f"页面={self.page.url}；文案={item['text']!r}；地址={resolved}；"
                    f"元素路径={evidence.get('selector', '未捕获')}"
                )
