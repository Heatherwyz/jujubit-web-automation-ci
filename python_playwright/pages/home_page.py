"""首页页面对象。

把访问首页、关闭优惠弹窗、打开导航等重复操作集中在这里，测试用例只保留
业务断言，定位器变化时也只需要修改这一处。
"""

import re
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

from playwright.sync_api import (
    Error as PlaywrightError,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    expect,
)


class SiteRateLimitError(RuntimeError):
    """站点返回 HTTP 429，当前用例无法完成业务校验。"""


# 判断一段失败详情是否属于站点频控。429 必须与 HTTP 语义相邻：裸数字会误判，
# 因为 traceback 里出现 429 行号（cart_page.py 有 2500+ 行）、
# "Timeout 30000ms exceeded ... at cart_page.py:1429"、"assert 429 == 430"
# 都是完全正常的失败内容。误判代价特别高——conftest 会把 detail 整段替换成
# 频控说明，原始错误信息直接丢失，报告里再也看不到真实失败原因。
RATE_LIMIT_DETAIL_PATTERN = re.compile(
    r"""
      http\s*/?\d*(?:\.\d+)?\s*429\b
    | \b429\s*(?:too\s+many\s+requests|frequency|rate)
    | (?:status(?:_code)?|code|响应|返回)\s*[=:：]?\s*429\b
    | \b429\s*=\s*[^\n]{0,100}?\.status\b
    | 访问频控
    | 频率限制
    | rate[ _-]?limit(?:ed|ing)?
    | too\s+many\s+requests
    | retry[- ]after
    """,
    re.I | re.X,
)


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
        # ``:visible`` 不能单独作为判断：真正拦截点击的可能是全屏 overlay，
        # 因此关闭逻辑还会结合 elementFromPoint 检查当前顶层命中元素。
        self.popup_root = page.locator(
            ".newsletter-popup-v2, .newsletter-popup--original"
        )
        self.welcome_popup = page.locator(
            ".newsletter-popup-v2:visible, .newsletter-popup--original:visible"
        )

    def open(self) -> None:
        """打开首页，并在站点返回 429 时限速等待后重试。

        HTTP 429 是站点对高频访问的频控信号，不是首页功能断言失败。默认模式
        会自动退避重试；带 ``--pw-manual-verification`` 时会显示浏览器，允许
        使用者手动完成网站要求的验证后再继续，脚本不会自动绕过验证。
        """
        existing_limit = getattr(self.config, "_jujubit_site_rate_limited", "")
        if existing_limit:
            raise SiteRateLimitError(existing_limit)
        retries = self._rate_limit_retries()
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
                    delay = self._retry_delay(attempt, response.headers.get("retry-after"))
                    print(f"首页触发 HTTP 429，等待 {delay:g} 秒后第 {attempt + 1} 次重试。")
                    time.sleep(delay)
                    continue
                reason = (
                    "首页访问被站点频控拦截：HTTP 429。"
                    "这不是页面功能缺陷；请稍后重试，或用 "
                    "`.venv/bin/python run_all.py --manual-verification` "
                    "在可见浏览器中手动完成网站要求的验证后继续。"
                )
                self.config._jujubit_site_rate_limited = reason
                raise SiteRateLimitError(reason)
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

    def _rate_limit_retries(self) -> int:
        """读取本次运行允许的 429 自动重试次数。"""
        return max(0, self.config.getoption("--pw-429-retries"))

    def _retry_delay(self, attempt: int, retry_after: Optional[str] = None) -> float:
        """优先遵循站点 Retry-After；缺失或异常时使用有界指数退避。"""
        try:
            delay = float(retry_after or "")
            if delay >= 0:
                return min(delay, 90.0)
        except (TypeError, ValueError):
            pass
        return min(15.0 * (2**attempt), 60.0)

    def _pace_site_request(self) -> None:
        """所有首页和站内链接请求共用一个节流器，降低连续访问频控风险。"""
        pacer = getattr(self.config, "_jujubit_site_pacer", None)
        if pacer is not None:
            pacer.wait()

    def pace_link_check_request(self) -> None:
        """兼容旧调用：批量扫描也使用与首页导航相同的全局限速器。"""
        self._pace_site_request()

    def get_with_rate_limit_retry(self, url: str, *, timeout: int):
        """以全局限速和退避重试获取站内页面。

        首页 fixture 与 REQ-04/REQ-15 的 HTTP 探测统一走这里：相同 Runner
        出口 IP 下不会出现“链接扫描刚结束就立即打开首页”的突发请求。重试耗尽
        时抛出专用异常，由 pytest 标记为“因 429 未完成”，而非业务失败。
        """
        retries = self._rate_limit_retries()
        for attempt in range(retries + 1):
            self._pace_site_request()
            try:
                response = self.page.request.get(
                    url,
                    fail_on_status_code=False,
                    timeout=timeout,
                )
            except PlaywrightError:
                # 网络/超时错误仍由调用方按原逻辑记录为页面检查异常，不能误标为 429。
                raise
            if response.status != 429:
                return response
            if attempt < retries:
                delay = self._retry_delay(attempt, response.headers.get("retry-after"))
                print(f"{url} 收到 HTTP 429，等待 {delay:g} 秒后第 {attempt + 1} 次重试。")
                time.sleep(delay)
        raise SiteRateLimitError(
            f"站点访问频控（HTTP 429）：{url} 在 {retries + 1} 次请求后仍被限制；"
            "本条用例未完成业务校验，不代表页面功能失败。"
        )

    def probe_internal_link(self, url: str) -> dict:
        """探测首页实际配置的站内链接，并在 PC/H5 间复用同一结果。

        两个端的 DOM 仍会分别采集和校验；缓存只避免同一个 URL 被重复下载两次。
        这样既不降低链接覆盖，又能减少 Shopify/WAF 将自动化当成批量爬取的风险。
        """
        cache = getattr(self.config, "_jujubit_link_probe_cache", {})
        if url in cache:
            cached = cache[url]
            if cached.get("rate_limited"):
                raise SiteRateLimitError(cached["rate_limited"])
            return cached

        last_error = None
        # 公网页面下载偶发超时；第二次使用更长时限，避免把已返回 200 的页面误报为坏链。
        for timeout in (8_000, 20_000):
            try:
                response = self.get_with_rate_limit_retry(url, timeout=timeout)
                result = {"status": response.status, "body": response.text()}
                cache[url] = result
                return result
            except SiteRateLimitError as error:
                # 本次套件内同一 URL 不再继续撞限流；后续端会得到同一“未完成”结论。
                cache[url] = {"rate_limited": str(error)}
                raise
            except PlaywrightError as error:
                last_error = error

        result = {
            "error": str(last_error).split("Call log:", 1)[0].strip()
            if last_error
            else "未取得响应",
        }
        # 网络超时是瞬态环境问题，不能跨 PC/H5 固化为相同失败；下一端仍可独立重试。
        return result

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

    def _popup_blocks_interaction(self) -> bool:
        """判断优惠弹窗或其遮罩是否仍会拦截真实用户点击。"""
        return bool(
            self.page.evaluate(
                """() => {
                    const candidates = [...document.querySelectorAll([
                        '.newsletter-popup-v2',
                        '.newsletter-popup--original',
                        '.newsletter-popup-v2__overlay',
                        '.newsletter-popup__overlay',
                        '.newsletter-popup-v2__close',
                        '.newsletter-popup--original .modal__close',
                        '.newsletter-popup-v2 button[aria-label*="Close"]',
                        '.newsletter-popup--original button[aria-label*="Close"]',
                        '.newsletter-popup-v2 .modal__close',
                        '.newsletter-popup--original .modal__close',
                    ].join(','))];

                    const isRendered = element => {
                        if (typeof element.checkVisibility === 'function'
                            && !element.checkVisibility({
                                // 透明但 pointer-events 仍开启的退出动画仍会拦截点击，
                                // 不能把它误判成已关闭。
                                checkOpacity: false,
                                checkVisibilityCSS: true,
                            })) return false;
                        const style = window.getComputedStyle(element);
                        const rect = element.getBoundingClientRect();
                        return style.display !== 'none'
                            && style.visibility !== 'hidden'
                            && style.pointerEvents !== 'none'
                            && rect.width > 1
                            && rect.height > 1
                            && rect.right > 0
                            && rect.bottom > 0
                            && rect.left < window.innerWidth
                            && rect.top < window.innerHeight;
                    };

                    const receivesPointer = element => {
                        if (!isRendered(element)) return false;
                        const rect = element.getBoundingClientRect();
                        const left = Math.max(0, rect.left);
                        const right = Math.min(window.innerWidth, rect.right);
                        const top = Math.max(0, rect.top);
                        const bottom = Math.min(window.innerHeight, rect.bottom);
                        const points = [
                            [(left + right) / 2, (top + bottom) / 2],
                            [left + 2, top + 2],
                            [right - 2, top + 2],
                            [left + 2, bottom - 2],
                            [right - 2, bottom - 2],
                        ];
                        return points.some(([x, y]) => {
                            const hit = document.elementFromPoint(x, y);
                            return Boolean(hit && (hit === element || element.contains(hit)));
                        });
                    };

                    return candidates.some(receivesPointer);
                }"""
            )
        )

    def _popup_close_controls(self):
        """返回所有可见关闭控件；多个主题变体并存时逐个尝试顶层控件。"""
        return self.popup_root.locator(
            "button[aria-label='Close']:visible, "
            "button[aria-label*='Close']:visible, "
            ".newsletter-popup-v2__close:visible, "
            ".newsletter-popup__close:visible, "
            ".modal__close:visible, "
            "[data-popup-close]:visible"
        )

    def _wait_for_popup_clear(self, timeout_ms: int = 3_000) -> bool:
        """等待关闭动画结束，并确认弹窗相关元素不再接收指针事件。"""
        deadline = time.monotonic() + max(0, timeout_ms) / 1_000
        while True:
            if not self._popup_blocks_interaction():
                return True
            if time.monotonic() >= deadline:
                return False
            self.page.wait_for_timeout(100)

    def popup_is_blocking(self) -> bool:
        """返回优惠弹窗或透明遮罩是否仍会拦截页面操作。"""
        return self._popup_blocks_interaction()

    def close_welcome_popup(self, *, observe_timeout: Optional[int] = None) -> bool:
        """关闭出现或遮挡点击的优惠弹窗，返回本次是否实际关闭。"""
        # 同一地址第一次最多观察 7 秒，覆盖线上延迟弹窗；后续调用只做快速复查。
        current_url = self.page.url
        wait_timeout = (
            observe_timeout
            if observe_timeout is not None
            else (7_000 if self._popup_checked_url != current_url else 500)
        )
        deadline = time.monotonic() + max(0, wait_timeout) / 1_000
        while not self._popup_blocks_interaction() and time.monotonic() < deadline:
            self.page.wait_for_timeout(100)
        if not self._popup_blocks_interaction():
            self._popup_checked_url = current_url
            return False
        # 页面脚本偶发晚于遮罩渲染完成。多个弹窗主题节点可能同时存在，逐个点击
        # 当前可见的真实关闭控件；绝不通过改样式或删除 DOM 绕过弹窗。
        last_error = None
        for attempt in range(2):
            controls = self._popup_close_controls()
            try:
                # 遮罩可能先出现、关闭按钮再由主题脚本挂载；先等真实控件可见。
                controls.first.wait_for(state="visible", timeout=3_000)
            except PlaywrightTimeoutError as error:
                last_error = error
                if attempt == 0:
                    self.page.wait_for_timeout(500)
                    continue
                break
            for close_button in controls.all():
                try:
                    close_button.click(timeout=3_000)
                except PlaywrightError as error:
                    # 被另一层弹窗覆盖的关闭按钮无法点击，继续尝试真正位于顶层的控件。
                    last_error = error
                    continue
                if self._wait_for_popup_clear():
                    self._popup_checked_url = current_url
                    return True
            if attempt == 0:
                self.page.wait_for_timeout(500)
        if not self._popup_close_controls().count():
            raise AssertionError("优惠弹窗遮罩出现，但未找到可操作的关闭按钮") from last_error
        raise AssertionError("优惠弹窗关闭后仍在遮挡页面操作") from last_error

    def close_popup_before_click(self) -> bool:
        """点击关键入口前再次观察延迟弹窗，避免遮罩在首次检查后才出现。"""
        # 当前 document 第一次已完整观察 7 秒后，后续关键点击只快速复查当前
        # 顶层遮罩；避免每个购物车动作都重复等待 4 秒。若尚未完整检查过该 URL，
        # 仍保留 4 秒窗口覆盖主题配置的 3 秒延迟弹窗。
        current_url = self.page.url
        observe_timeout = 500 if self._popup_checked_url == current_url else 4_000
        return self.close_welcome_popup(observe_timeout=observe_timeout)

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

    def click_unobstructed(self, locator: Locator, description: str) -> None:
        """在元素内寻找真实可点击点，再用鼠标或触屏完成用户点击。

        H5 抽屉顶部可能与固定 Header 局部重叠。Playwright 默认点击中心点时会被
        Header 拦截，但链接下沿仍是用户可以点击的区域；这里通过
        ``elementFromPoint`` 检查多个内缩点，只点击确实命中目标或其子元素的点。
        若整个目标都被遮挡则明确失败，绝不使用 ``force=True`` 掩盖真实故障。
        """
        target = locator.first
        target.wait_for(state="visible", timeout=10_000)
        hit_test = target.evaluate(
            """element => {
                const rect = element.getBoundingClientRect();
                if (rect.width <= 1 || rect.height <= 1) {
                    return { point: null, blocker: '目标元素没有可点击尺寸' };
                }

                // 中心点优先；随后检查四角和 3×5 网格中的内缩点。网格足以
                // 覆盖“上半部分被固定 Header 压住、下沿仍可点击”的移动端布局。
                const fractions = [
                    [0.5, 0.5],
                    [0.12, 0.12], [0.88, 0.12],
                    [0.12, 0.88], [0.88, 0.88],
                    ...[0.2, 0.5, 0.8].flatMap(x =>
                        [0.2, 0.35, 0.5, 0.65, 0.8].map(y => [x, y])
                    ),
                ];
                const seen = new Set();
                let blocker = '';
                for (const [xFraction, yFraction] of fractions) {
                    const x = Math.min(window.innerWidth - 1, Math.max(0,
                        rect.left + rect.width * xFraction));
                    const y = Math.min(window.innerHeight - 1, Math.max(0,
                        rect.top + rect.height * yFraction));
                    const key = `${Math.round(x)}:${Math.round(y)}`;
                    if (seen.has(key)) continue;
                    seen.add(key);
                    const hit = document.elementFromPoint(x, y);
                    if (hit && (hit === element || element.contains(hit))) {
                        return { point: { x, y }, blocker: '' };
                    }
                    if (hit && !blocker) {
                        blocker = hit.id
                            ? `${hit.tagName.toLowerCase()}#${hit.id}`
                            : `${hit.tagName.toLowerCase()}.${[...hit.classList].slice(0, 3).join('.')}`;
                    }
                }
                return { point: null, blocker: blocker || '视口内没有命中元素的点' };
            }"""
        )
        point = hit_test.get("point")
        if not point:
            raise AssertionError(
                f"{description}无法真实点击：控件全部被遮挡；"
                f"顶层元素={hit_test.get('blocker', '未知')}"
            )

        # H5 Context 配置了触屏能力；桌面端使用鼠标。点击后页面可能立即导航，
        # 因此这里不再读取 DOM，避免把正常的 execution context 销毁当成失败。
        has_touch = bool(self.page.evaluate("() => navigator.maxTouchPoints > 0"))
        if has_touch:
            self.page.touchscreen.tap(point["x"], point["y"])
        else:
            self.page.mouse.click(point["x"], point["y"])

    def active_hero_cta(self) -> Locator:
        """返回当前激活 Hero 轮播项中真正提供给用户点击的 CTA。"""
        active_slide = self.page.get_by_role("region", name="Banner").locator(
            "[data-banner-slide].is-active"
        )
        expect(active_slide).to_have_count(1)
        # 主题的整张 slide 链接可能包含标题和 CTA，accessible name 并不等于
        # 按钮文案；以明确的 CTA 标记和可见按钮文字锁定业务入口，避免误选
        # 被标题覆盖的背景锚点。
        cta_label = self.page.locator(".jjb-banner__btn:visible").filter(
            has_text=re.compile(r"^\s*Create\s+Your\s+Own\s*$", re.I)
        )
        cta = active_slide.locator(
            'a[data-gtm-item="hero-cta"]:visible'
        ).filter(has=cta_label)
        expect(cta).to_have_count(1)
        return cta.first

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
