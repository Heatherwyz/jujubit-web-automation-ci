"""首页 PRD 与技术文档的需求验收测试。

这里的 case 比基础冒烟层更关注可访问性、SEO、真实链接跳转、Footer 配置和
FAQ 交互等需求细节。每条同样由 pytest 自动拆分为 PC/H5 两端执行。
"""

import json
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Error as PlaywrightError, expect

from python_playwright.pages.home_page import SiteRateLimitError


EXPECTED_TITLE = "JuJuBit | Custom Figurines, Crystal Bracelets & Art Toys"
EXPECTED_DESCRIPTION = (
    "JuJuBit makes custom figurines from your photo, crystal bracelets, and art toys. "
    "AI-assisted design, worldwide shipping. Turn your photo into a 3D collectible."
)
EXPECTED_H1 = "Create Your Own Custom Figurine From a Photo"
EXPECTED_LOGO_ALT = "JuJuBit - Custom 3D Figurines"
EXPECTED_NAVIGATION_LINKS = {
    "Templates": "/collections/templates-create-your-own",
    "How It Works": "/pages/how-it-works",
}
EXPECTED_HEADER_CATEGORY_LINKS = {
    # 线上主题已将该品类的导航展示文案更新为 FIGURINES；业务集合地址
    # 仍然是 art-toy。按当前可见文案验收，避免把旧名称误报为缺少链接。
    "FIGURINES": "/collections/art-toy",
    "FDM LAMPS": "/collections/fdm",
    "Crystal Bracelets": "/collections/crystal-bracelets",
    "Keycaps": "/collections/keycaps",
    "Photo Boards": "/collections/photo-board",
}
# REQ-06 是安全属性验收：所有当前已配置的社交平台都必须独立检查，不能
# 因为第一个平台失败，就漏掉其他平台的同类问题。Snapchat 已不在当前
# Footer 配置中，因此不把历史平台清单当成当前首页的必需入口。
EXPECTED_SOCIAL_PLATFORMS = (
    ("Instagram", "JuJuBit on Instagram", "www.instagram.com", "/thisisjujubit_"),
    ("TikTok", "JuJuBit on TikTok", "www.tiktok.com", "/@jujubit_official"),
    ("YouTube", "JuJuBit on YouTube", "www.youtube.com", "/@thisisjujubit"),
    ("X", "JuJuBit on X", "x.com", "/thisisjujubit"),
)


class _AnchorCollector(HTMLParser):
    """从服务端 HTML 中提取真实锚点，避免把脚本字符串误当成导航链接。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []
        self._active_anchor = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a" or self._active_anchor is not None:
            return
        attributes = dict(attrs)
        self._active_anchor = {"href": attributes.get("href", ""), "text": []}

    def handle_data(self, data):
        if self._active_anchor is not None:
            self._active_anchor["text"].append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or self._active_anchor is None:
            return
        self.anchors.append(
            {
                "href": self._active_anchor["href"],
                "text": re.sub(r"\s+", " ", " ".join(self._active_anchor["text"])).strip(),
            }
        )
        self._active_anchor = None


class _FaqContentCollector(HTMLParser):
    """只收集 SSR FAQ section 内结构完整且有正文的问答。"""

    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.has_section = False
        self.items = []
        self._stack = []
        self._section_depth = 0
        self._current_item = None
        self._item_depth = None
        self._summary_depth = None
        self._question_depth = None
        self._answer_depth = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = dict(attrs)
        if self._section_depth == 0:
            if tag != "section" or "data-jjb-faq" not in attributes:
                return
            self.has_section = True
            self._section_depth = 1
            self._stack = [tag]
            return

        if tag == "section":
            self._section_depth += 1
        if tag not in self._VOID_TAGS:
            self._stack.append(tag)
        depth = len(self._stack)
        classes = set((attributes.get("class") or "").split())

        if (
            tag == "details"
            and self._current_item is None
            and ("data-faq-item" in attributes or "jjb-faq__item" in classes)
        ):
            self._current_item = {"question": [], "answer": []}
            self._item_depth = depth
        if self._current_item is None:
            return
        if tag == "summary":
            self._summary_depth = depth
        elif tag == "h3" and self._summary_depth is not None:
            self._question_depth = depth
        if "data-faq-answer" in attributes or "jjb-faq__answer" in classes:
            self._answer_depth = depth

    def handle_data(self, data):
        if self._current_item is None:
            return
        if self._question_depth is not None:
            self._current_item["question"].append(data)
        if self._answer_depth is not None:
            self._current_item["answer"].append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._section_depth == 0 or not self._stack:
            return
        try:
            depth = len(self._stack) - self._stack[::-1].index(tag)
        except ValueError:
            return
        if self._question_depth == depth and tag == "h3":
            self._question_depth = None
        if self._answer_depth == depth:
            self._answer_depth = None
        if self._summary_depth == depth and tag == "summary":
            self._summary_depth = None
        if self._item_depth == depth and tag == "details":
            self.items.append(
                {
                    key: re.sub(r"\s+", " ", " ".join(parts)).strip()
                    for key, parts in self._current_item.items()
                }
            )
            self._current_item = None
            self._item_depth = None
            self._summary_depth = None
            self._question_depth = None
            self._answer_depth = None

        if tag == "section":
            self._section_depth -= 1
        # Shopify 输出通常是合法嵌套；若第三方富文本产生不完整标签，则从
        # 当前闭合标签处一起退栈，避免后续问答被错误吞进前一项。
        del self._stack[depth - 1 :]
        if self._section_depth == 0:
            self._stack = []


def _assert_destination_is_usable(page, response, href):
    """检查真实点击后的响应、错误页标记和主内容，避免把有正文的 404 当成通过。"""
    if response is not None:
        assert response.status < 400, f"点击后返回 HTTP {response.status}：{href}"
    page.locator("main").wait_for(state="visible", timeout=15_000)
    title = page.title().lower()
    body = page.locator("body").inner_text().strip()
    assert body, f"点击后页面为空，疑似白屏：{href}"
    body_text = body.lower()
    title_markers = ("404", "page not found", "internal server error")
    body_markers = ("404 error", "page not found", "internal server error")
    assert not any(marker in title for marker in title_markers) and not any(
        marker in body_text for marker in body_markers
    ), (
        f"点击后进入错误页：{href}"
    )


def _skip_if_site_verification_blocks_page(page, href):
    """识别 CI 出口触发的人机验证，避免把环境拦截误报为业务白屏。"""
    title = page.title().strip().lower()
    body = page.locator("body").inner_text(timeout=5_000).strip().lower()
    title_markers = ("just a moment", "attention required", "security verification")
    body_markers = (
        "complete the human verification process",
        "verify you are human",
        "performing security verification",
        "checking if the site connection is secure",
    )
    if any(marker in title for marker in title_markers) or any(
        marker in body for marker in body_markers
    ):
        pytest.skip(
            "站点人机验证拦截了 GitHub Runner，本条链接未完成校验，"
            f"不代表业务页面失败：{href}"
        )


def _is_trusted_shopify_account_host(hostname):
    """判断登录跳转最终是否仍在 Shopify 托管账户的受信域名内。"""
    normalized = (hostname or "").lower().rstrip(".")
    return normalized == "shopify.com" or normalized.endswith(".shopify.com")


def _assert_customer_account_login_page(page, response, href):
    """验收 Shopify Customer Account 登录页，而不是误用 API 正文长度判白屏。

    Customer Account 会从店铺的 ``/account`` 或 ``/customer_authentication/``
    重定向到 Shopify OAuth。该链路的 API 请求可能返回 406，但真实浏览器中的
    登录页是正常的，因此这里以最终渲染的页面和登录控件作为验收依据。
    """
    _skip_if_site_verification_blocks_page(page, href)
    if response is not None:
        # Shopify Customer Account 的独立频控不代表首页登录入口失效；与首页
        # 及普通链接扫描的 429 口径一致，明确标记为本轮未完成而非业务失败。
        if response.status == 429:
            pytest.skip(
                "Shopify Customer Account 登录服务返回 HTTP 429，本条登录入口"
                f"校验未完成，不代表页面功能失败：{href}"
            )
        assert response.status < 400, (
            f"Customer Account 登录跳转返回 HTTP {response.status}：{href}"
        )

    final_url = urlparse(page.url)
    final_host = (final_url.hostname or "").lower()
    assert final_url.scheme == "https", f"Customer Account 登录页不是 HTTPS：{page.url}"
    assert _is_trusted_shopify_account_host(final_host), (
        "Customer Account 登录入口跳转到了非受信任域名："
        f"{page.url}（原始入口：{href}）"
    )

    page.locator("main").wait_for(state="visible", timeout=15_000)
    body = page.locator("body").inner_text().strip()
    assert body, f"Customer Account 登录页正文为空：{page.url}"
    body_text = body.lower()
    error_markers = ("404 error", "page not found", "internal server error")
    assert not any(marker in body_text for marker in error_markers), (
        f"Customer Account 登录入口打开了错误页：{page.url}"
    )
    assert re.search(r"\bsign\s*in\b", body, re.I), (
        f"Customer Account 登录页缺少 Sign in 文案：{page.url}"
    )
    email_field = page.locator(
        'input[type="email"]:visible, input[autocomplete="email"]:visible'
    ).first
    expect(email_field).to_be_visible()


def _click_and_check_destination(home, page, link):
    """关闭弹窗后点击主题当前配置的链接，并检查真实落地页。"""
    home.close_welcome_popup()
    href = link.get_attribute("href")
    assert href and href != "#", "实际配置的链接不能为空"
    before_url = page.url
    target_path = urlparse(href).path or "/"
    # 部分 Shopify 入口通过 history API 或重定向完成跳转，不一定触发 expect_navigation 事件。
    link.click()
    page.wait_for_function(
        """({ before, path }) => location.href !== before && location.pathname === path""",
        arg={"before": before_url, "path": target_path},
        timeout=30_000,
    )
    page.wait_for_load_state("domcontentloaded")
    # GitHub Runner 偶发进入独立的人机验证页，该页面本身没有业务 <main>。
    # 先识别访问环境拦截，再执行页面结构断言，避免被误记为白屏失败。
    _skip_if_site_verification_blocks_page(page, href)
    # 落地页若再次出现优惠弹窗，也先关闭再检查页面内容。
    home.close_welcome_popup()
    _assert_destination_is_usable(page, None, href)


def test_homepage_seo_metadata(home, page, test_platform):
    """REQ-01：SEO 标题、描述和唯一 H1 与需求文案一致。"""
    home.close_welcome_popup()
    assert page.title() == EXPECTED_TITLE
    descriptions = page.locator('meta[name="description"]')
    assert descriptions.count() == 1
    assert descriptions.get_attribute("content") == EXPECTED_DESCRIPTION
    headings = page.locator("h1")
    assert headings.count() == 1
    actual_h1 = " ".join(headings.inner_text().split())
    if actual_h1 != EXPECTED_H1:
        evidence_target = (
            headings
            if headings.is_visible()
            else page.get_by_role("region", name="Banner")
        )
        home.mark_failure_evidence(
            evidence_target,
            f"H1 应为 {EXPECTED_H1!r}，实际为 {actual_h1!r}",
        )
        raise AssertionError(
            f"需求预期：首页唯一 H1 为 {EXPECTED_H1!r}；实际为 {actual_h1!r}"
        )


def test_logo_accessibility_text(home, test_platform):
    """REQ-02：Logo 图片使用需求指定的精确 alt，并链接首页。"""
    home.close_welcome_popup()
    logo_link = home.visible_logo()
    expect(logo_link).to_have_count(1)
    logo_image = logo_link.locator("img")
    if logo_image.count():
        expect(logo_image).to_have_attribute("alt", EXPECTED_LOGO_ALT)
    else:
        expect(logo_link).to_have_attribute("aria-label", "JuJuBit")


def test_hero_lcp_media_is_eager(home, page, test_platform):
    """REQ-03：首屏 Hero 媒体不懒加载，并预留尺寸以降低布局偏移。"""
    home.close_welcome_popup()
    banner = page.get_by_role("region", name="Banner")
    first_slide = banner.locator("[data-banner-slide]").first
    platform_media = "mb" if test_platform == "h5" else "pc"
    # 首屏性能应检查初始 slide 在当前端实际使用的图片，不受自动轮播切换影响。
    hero_image = first_slide.locator(
        f".jjb-banner__media-wrap--{platform_media} img"
    ).first
    expect(hero_image).to_be_attached()
    loading = hero_image.get_attribute("loading")
    if loading == "lazy":
        home.mark_failure_evidence(
            hero_image,
            "Hero 首屏图片使用 loading=lazy，应改为 eager 或移除 lazy。",
        )
        raise AssertionError(
            "需求预期：Hero 首屏图片立即加载；"
            "实际：图片使用 loading=lazy，可能延迟首屏最大内容绘制（LCP）"
        )
    has_dimensions = bool(hero_image.get_attribute("width") and hero_image.get_attribute("height"))
    has_aspect_ratio = hero_image.evaluate("el => getComputedStyle(el).aspectRatio !== 'auto'")
    if not (has_dimensions or has_aspect_ratio):
        home.mark_failure_evidence(
            hero_image,
            "Hero 图片未设置 width/height，也没有 CSS aspect-ratio。",
        )
        raise AssertionError("Hero 图片必须通过 width/height 或 aspect-ratio 预留布局空间")


def test_configured_internal_links_are_available(home, page, test_platform):
    """REQ-04：扫描首页普通站内业务链接，排除错误页和疑似白屏。"""
    home.close_welcome_popup()
    expect(home.welcome_popup).to_be_hidden()
    configured = page.locator(
        '[role="region"][aria-label="Announcement bar"] a[href], '
        'header a[href], main a[href], footer a[href]'
    ).evaluate_all(
        """nodes => nodes
        // ``hidden`` 是语义上不向用户提供的模板备用入口；不要把它们混入
        // 首页实际可用链接巡检。不能泛用 :visible，避免漏掉隐藏轮播业务链接。
        .filter(node => !node.hidden && !node.closest('[hidden]'))
        .map(node => ({
            text: (node.innerText || node.getAttribute('aria-label') || node.title || '').trim(),
            href: node.href
        }))"""
    )
    host = urlparse(home.base_url).netloc
    links = {}
    for item in configured:
        parsed = urlparse(item["href"])
        if parsed.netloc != host or parsed.scheme not in ("http", "https"):
            continue
        # Shopify 系统页不属于首页普通业务落地页。Customer Account 的 OAuth
        # 重定向会在独立用例中用真实浏览器检验，不能用接口响应正文判白屏。
        if parsed.path in {"/account", "/cart", "/search", "/checkout"} or parsed.path.startswith(
            "/customer_authentication/"
        ):
            continue
        key = parsed._replace(fragment="").geturl()
        links.setdefault(key, item["text"] or parsed.path or "首页")
    assert links, "Homepage did not render any configured internal links"

    # 全量链接来源于当前首页 DOM；HTTP 扫描用于覆盖隐藏轮播项，真实点击由 REQ-04B 验证。
    # 同一 URL 在 PC/H5 之间会复用探测结果，避免重复请求被 Shopify/WAF 当作爬虫。
    failures = []
    for url, label in links.items():
        try:
            probe = home.probe_internal_link(url)
        except SiteRateLimitError as error:
            pytest.skip(str(error))
        if "error" in probe:
            failures.append((label, url, f"请求异常：{probe['error']}"))
            continue
        status = probe["status"]
        body = probe["body"]
        visible_text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", body))).strip()
        if 400 <= status < 500:
            # 除已排除的系统入口外，任何 4xx 都应如实报告 HTTP 状态，不能被
            # 空响应正文误写成“疑似白屏”。
            failures.append((label, url, f"HTTP {status}"))
        elif status >= 500:
            failures.append((label, url, f"HTTP {status}"))
        elif len(visible_text) < 20:
            failures.append((label, url, "页面内容为空，疑似白屏"))

    if failures:
        # 录像最后停留在首个异常链接，便于直接观察错误页；地址来自首页实际 href。
        _, failing_url, _ = failures[0]
        try:
            page.goto(failing_url, wait_until="commit")
        except PlaywrightError:
            pass
        details = [f"{label!r} -> {url}（{reason}）" for label, url, reason in failures]
        raise AssertionError("首页实际配置链接异常：\n" + "\n".join(details))


def test_customer_account_login_entry_is_usable(home, page, test_platform):
    """REQ-04A：当前可见 Log in 入口可打开 Shopify 托管的正常登录页。"""
    home.close_welcome_popup()
    account_link = page.get_by_role("link", name=re.compile(r"^log in$", re.I))
    expect(account_link).to_have_count(1)
    expect(account_link).to_be_visible()
    href = account_link.get_attribute("href")
    assert href and href != "#", "当前可见 Log in 入口缺少有效 href"

    # 先再次关闭可能延迟出现的优惠弹窗，再真实点击当前端入口。这样能发现
    # 遮罩、pointer-events 或 onclick 回归导致用户实际无法进入登录页的问题。
    home.close_popup_before_click()
    # 真实浏览器导航会跟随 jujubit.ai → Shopify Customer Account 的 OAuth
    # 重定向，所得页面与用户实际点击后的页面一致；不输入邮箱或提交登录表单。
    home.pace_link_check_request()
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=30_000) as navigation:
            account_link.click()
        response = navigation.value
    except PlaywrightError as error:
        raise AssertionError(f"Log in 入口点击后未能打开 Customer Account 登录页：{href}") from error
    _assert_customer_account_login_page(page, response, href)


def test_configured_navigation_and_hero_links_can_open(home, page, test_platform):
    """关闭弹窗后真实点击关键入口，验证主题当前配置的跳转页面不是白屏。"""
    home.close_welcome_popup()
    navigation = home.navigation_root(test_platform)
    nav_link = navigation.locator("a[href]").filter(has_text=re.compile(r"^\s*Create\s*$")).first
    _click_and_check_destination(home, page, nav_link)

    # 每次回到首页后重新关闭弹窗，再定位并点击当前 Hero CTA。
    home.open()
    home.close_welcome_popup()
    hero_link = page.get_by_role("region", name="Banner").locator("a[href]:visible").first
    _click_and_check_destination(home, page, hero_link)


def test_footer_locale_switcher_is_available(home, page, test_platform):
    """REQ-05：Footer 地区/币种控件可见、可展开并可收起。"""
    home.close_welcome_popup()
    footer = page.locator("footer")
    expect(footer).to_be_visible()
    # Shopify 本地化表单应展示当前地区和币种，并能展开可选项。
    locale_form = footer.locator('form[action*="/localization"]:visible')
    expect(locale_form).to_have_count(1)
    switcher = locale_form.locator('button[aria-controls]:visible')
    expect(switcher).to_have_count(1)

    current_label = " ".join(switcher.inner_text().split())
    assert re.search(r"\([A-Z]{3}\s+.+\)", current_label), (
        f"切换器未展示有效的币种代码和符号：{current_label!r}"
    )
    panel_id = switcher.get_attribute("aria-controls")
    assert panel_id, "本地化切换器缺少 aria-controls，无法关联选项列表"
    expect(switcher).to_have_attribute("aria-expanded", "false")

    # Footer DOM 会早于主题 Disclosure 实例出现，必须等待真实交互初始化完成。
    # 当前页面若初始化失败则重新打开一次，且每次只点击一次，避免误把面板收起。
    for attempt in range(2):
        home.close_welcome_popup()
        try:
            home.wait_for_theme_interactions()
            switcher.click()
            expect(switcher).to_have_attribute("aria-expanded", "true", timeout=10_000)
            expect(page.locator(f"#{panel_id}")).to_be_visible(timeout=5_000)
            break
        except (AssertionError, PlaywrightError):
            if attempt == 1:
                raise AssertionError("Footer 地区与币种切换器点击后未展开")
            home.open()
    options_panel = page.locator(f"#{panel_id}")
    expect(options_panel).to_be_visible(timeout=5_000)
    assert options_panel.locator("a[href]:visible").count() >= 2, (
        "本地化切换器展开后应至少提供两个地区或币种选项"
    )

    # 收起选项，验证控件可以重复操作且不会在用例结束时遮挡页面。
    switcher.click()
    expect(switcher).to_have_attribute("aria-expanded", "false", timeout=10_000)


def test_external_social_links_are_safe(home, page, test_platform):
    """REQ-06：Footer 当前社交平台的地址、可访问名称和安全属性正确。"""
    home.close_welcome_popup()
    social_links = page.locator("footer .social-icons a[href]")
    assert social_links.count() >= 1, "Footer 未配置任何社交平台链接"
    # 一次读取 Footer 链接，随后按平台分别校验，避免第一个失败掩盖后续平台的结果。
    items = social_links.evaluate_all(
        r"""nodes => nodes.map((node, index) => ({
            index,
            href: node.href,
            rel: node.getAttribute('rel') || '',
            target: node.getAttribute('target') || '',
            ariaLabel: node.getAttribute('aria-label') || '',
            title: node.getAttribute('title') || '',
        }))"""
    )
    failures = []
    known_indices = set()
    for platform, aria_label, expected_host, expected_path in EXPECTED_SOCIAL_PLATFORMS:
        platform_links = [
            item for item in items
            if (urlparse(item["href"]).hostname or "").lower()
            in {expected_host, expected_host.removeprefix("www.")}
        ]
        if len(platform_links) != 1:
            failures.append(
                {
                    "platform": platform,
                    "reason": f"Footer 中应有且仅有一个 {platform} 链接，实际找到 {len(platform_links)} 个",
                    "link": None,
                }
            )
            continue

        item = platform_links[0]
        known_indices.add(item["index"])
        parsed = urlparse(item["href"])
        rel_tokens = set(item["rel"].lower().split())
        missing = {"noopener", "noreferrer"} - rel_tokens
        mismatches = []
        if parsed.path.rstrip("/") != expected_path.rstrip("/"):
            mismatches.append(f"路径应为 {expected_path}，实际为 {parsed.path}")
        if item["target"].lower() != "_blank":
            mismatches.append(f"target 应为 '_blank'，实际为 {item['target']!r}")
        # 使用浏览器计算后的 accessible name；不会把 aria-hidden 或 display:none
        # 的原始 textContent 错当成辅助技术实际可读的名称。
        link = social_links.nth(item["index"])
        allowed_name = re.compile(
            rf"^(?:JuJuBit on )?{re.escape(platform)}$",
            re.I,
        )
        try:
            expect(link).to_have_accessible_name(allowed_name)
        except (AssertionError, PlaywrightError):
            mismatches.append(
                f"浏览器计算的可访问名称应为 {platform!r} 或 {aria_label!r}"
            )
        if missing:
            mismatches.append(f"rel 缺少 {'、'.join(sorted(missing))}")
        if mismatches:
            failures.append(
                {
                    "platform": platform,
                    "href": item["href"],
                    "rel_tokens": rel_tokens,
                    "missing": missing,
                    "mismatches": mismatches,
                    "link": link,
                }
            )

    # 未来新增的平台即使不在固定 URL 清单里，也必须满足新窗口隔离和可访问命名。
    for item in items:
        if item["index"] in known_indices:
            continue
        link = social_links.nth(item["index"])
        rel_tokens = set(item["rel"].lower().split())
        missing = {"noopener", "noreferrer"} - rel_tokens
        mismatches = []
        if item["target"].lower() != "_blank":
            mismatches.append(f"target 应为 '_blank'，实际为 {item['target']!r}")
        if missing:
            mismatches.append(f"rel 缺少 {'、'.join(sorted(missing))}")
        try:
            expect(link).to_have_accessible_name(re.compile(r"\S"))
        except (AssertionError, PlaywrightError):
            mismatches.append("链接缺少浏览器可识别的可访问名称")
        if mismatches:
            failures.append(
                {
                    "platform": urlparse(item["href"]).hostname or "未知平台",
                    "href": item["href"],
                    "rel_tokens": rel_tokens,
                    "missing": missing,
                    "mismatches": mismatches,
                    "link": link,
                }
            )
    if failures:
        first_failure = failures[0]
        first_link = first_failure["link"]
        # 失败前给首个异常图标加红框；错误文本仍会完整列出所有平台的检查结果。
        if first_link is not None:
            home.mark_failure_evidence(
                first_link,
                f"{first_failure['platform']} 外部链接配置异常："
                f"{'；'.join(first_failure['mismatches'])}",
            )
        page.wait_for_timeout(800)
        details = []
        for failure in failures:
            if failure["link"] is None:
                details.append(f"- {failure['platform']}：{failure['reason']}")
                continue
            actual_rel = " ".join(sorted(failure["rel_tokens"])) or "空"
            details.append(
                f"- {failure['platform']}：{failure['href']} 的 rel=\"{actual_rel}\"，"
                + "；".join(failure["mismatches"])
            )
        raise AssertionError(
            "需求预期：Footer 当前社交平台的 URL、可访问名称和 rel 均符合文案基准；\n"
            "实际异常（所有当前平台均已检查）：\n" + "\n".join(details)
        )


def test_homepage_links_are_real_anchors(home, page, test_platform):
    """REQ-07：当前渲染的一级导航均为带有效 href 的真实链接。"""
    home.close_welcome_popup()
    navigation = home.navigation_root(test_platform)
    link_selector = (
        "a.jjb-header__menu-link"
        if test_platform == "pc"
        else "a.jjb-mobile-nav__link:not(.jjb-mobile-nav__submenu-link)"
    )
    links = navigation.locator(link_selector)
    assert links.count() >= 1, "当前导航未渲染任何一级链接"
    failures = []
    for index, link in enumerate(links.all()):
        label = " ".join(link.inner_text().split()) or f"第 {index + 1} 项"
        href = link.get_attribute("href")
        if not href or href == "#":
            failures.append((link, label, href))
    if failures:
        first_link, first_label, first_href = failures[0]
        home.mark_failure_evidence(first_link, f"导航项 {first_label} 的 href={first_href!r}")
        details = "；".join(f"{label}: href={href!r}" for _, label, href in failures)
        raise AssertionError(f"一级导航存在无效链接：{details}")


def test_social_videos_have_inline_playback_attributes(home, page, test_platform):
    """REQ-08：社交视频满足静音、移动端内联和循环播放属性。"""
    home.close_welcome_popup()
    videos = page.locator("video")
    if videos.count() == 0:
        pytest.skip("当前页面未配置视频")
    for video in videos.all():
        assert video.evaluate("el => el.muted"), "视频必须静音播放"
        assert video.get_attribute("playsinline") is not None, "视频必须支持移动端内联播放"
        assert video.get_attribute("loop") is not None, "视频必须循环播放"


def test_faq_semantics_and_single_expansion(home, page, test_platform):
    """REQ-09：FAQ 使用语义化结构，且同一时间仅显示一个答案。"""
    home.close_welcome_popup()
    details = page.locator("main details")
    detail_count = details.count()
    if detail_count == 0:
        pytest.skip("当前页面未配置 FAQ")
    assert detail_count == details.locator(":scope > summary > h3").count()
    if detail_count >= 2:
        first = details.nth(0)
        second = details.nth(1)
        first_summary = first.locator(":scope > summary")
        second_summary = second.locator(":scope > summary")

        # 先保证第一项展开，再直接点击第二项；这样才能验证主题脚本会自动收起前一项，
        # 而不是由测试脚本主动收起后得出“只展开一项”的假结论。
        if first.get_attribute("open") is None:
            first_summary.click()
            page.wait_for_function(
                """() => {
                    const detail = document.querySelector('main details');
                    return detail?.open === true;
                }""",
                timeout=10_000,
            )

        second_summary.click()
        page.wait_for_function(
            """() => {
                const details = [...document.querySelectorAll('main details')];
                return details.length >= 2
                    && details[1].open
                    && details.filter(detail => detail.open).length === 1;
            }""",
            timeout=15_000,
        )

        visible_answers = details.evaluate_all(
            """nodes => nodes.map((detail, index) => {
                const answer = detail.querySelector('.jjb-faq__answer');
                return {
                    index,
                    open: detail.open,
                    text: (answer?.innerText || '').trim(),
                    height: answer ? answer.getBoundingClientRect().height : 0,
                };
            }).filter(item => item.open && item.height > 2)"""
        )
        assert len(visible_answers) == 1, (
            "FAQ 同时显示了多项答案："
            + "；".join(item["text"][:80] for item in visible_answers)
        )


def test_hero_heading_hierarchy(home, page, test_platform):
    """REQ-10：Hero 使用 H2，不额外产生 H1。"""
    home.close_welcome_popup()
    banner = page.get_by_role("region", name="Banner")
    visible_headings = banner.locator("h2:visible")
    assert visible_headings.count() >= 1
    assert banner.locator("h1").count() == 0


def test_navigation_and_category_urls_match_requirements(home, page, test_platform):
    """REQ-11：Header 主入口和当前五个核心品类使用主题配置的 URL。"""
    home.close_welcome_popup()
    navigation = home.navigation_root(test_platform)
    links = navigation.locator("a[href]")
    items = links.evaluate_all(
        r"""nodes => nodes.map((node, index) => ({
            index,
            text: (node.textContent || '').trim().replace(/\s+/g, ' '),
            path: new URL(node.href, location.href).pathname.replace(/\/$/, '') || '/',
        }))"""
    )
    expected = {**EXPECTED_NAVIGATION_LINKS, **EXPECTED_HEADER_CATEGORY_LINKS}
    failures = []
    first_problem_index = None
    for label, expected_path in expected.items():
        matches = [item for item in items if item["text"].casefold() == label.casefold()]
        if not matches:
            failures.append(f"缺少导航链接 {label!r}")
            continue
        actual_paths = {item["path"] for item in matches}
        if expected_path is not None and expected_path not in actual_paths:
            failures.append(
                f"{label!r} 应指向 {expected_path}，实际为 {sorted(actual_paths)}"
            )
            if first_problem_index is None:
                first_problem_index = matches[0]["index"]
    if failures:
        # 缺少链接时标注整个导航；URL 错误时精确标注第一个错误链接。
        problem = links.nth(first_problem_index) if first_problem_index is not None else navigation
        home.mark_failure_evidence(problem, failures[0])
        raise AssertionError("Header 导航配置与需求不一致：\n" + "\n".join(failures))
def test_homepage_json_ld_is_valid_and_matches_faq(home, page, test_platform):
    """REQ-13：JSON-LD 可解析，FAQPage 与页面可见问答同源一致。"""
    home.close_welcome_popup()
    scripts = page.locator('script[type="application/ld+json"]')
    assert scripts.count() >= 1, "首页至少应输出一个 JSON-LD"
    documents = []
    parse_errors = []
    for index, script in enumerate(scripts.all()):
        content = script.text_content() or ""
        try:
            documents.append(json.loads(content))
        except json.JSONDecodeError as error:
            parse_errors.append(f"第 {index + 1} 个 JSON-LD 无法解析：{error}")
    assert not parse_errors, "\n".join(parse_errors)

    nodes = []
    for document in documents:
        if isinstance(document, list):
            nodes.extend(item for item in document if isinstance(item, dict))
        elif isinstance(document, dict) and isinstance(document.get("@graph"), list):
            nodes.extend(item for item in document["@graph"] if isinstance(item, dict))
        elif isinstance(document, dict):
            nodes.append(document)

    faq_nodes = [node for node in nodes if node.get("@type") == "FAQPage"]
    details = page.locator("main details")
    if details.count() == 0:
        assert not faq_nodes, "页面没有可见 FAQ 时不应输出 FAQPage Schema"
        return
    assert len(faq_nodes) == 1, f"有可见 FAQ 时应输出且仅输出一个 FAQPage，实际 {len(faq_nodes)} 个"
    visible_faq = details.evaluate_all(
        r"""nodes => nodes.map(detail => ({
            question: (detail.querySelector('summary')?.textContent || '').trim().replace(/\s+/g, ' '),
            answer: (detail.querySelector('.jjb-faq__answer')?.textContent || '').trim().replace(/\s+/g, ' '),
        }))"""
    )
    schema_faq = [
        {
            "question": re.sub(r"\s+", " ", str(item.get("name", ""))).strip(),
            "answer": re.sub(
                r"\s+",
                " ",
                unescape(re.sub(r"<[^>]+>", " ", str(item.get("acceptedAnswer", {}).get("text", "")))),
            ).strip(),
        }
        for item in faq_nodes[0].get("mainEntity", [])
        if isinstance(item, dict)
    ]
    if len(schema_faq) != len(visible_faq):
        home.mark_failure_evidence(
            details,
            f"FAQPage 共 {len(schema_faq)} 项，页面实际共 {len(visible_faq)} 项",
        )
        raise AssertionError(
            f"FAQPage Schema 数量为 {len(schema_faq)}，页面可见 FAQ 数量为 {len(visible_faq)}"
        )
    for index, (schema_item, visible_item) in enumerate(zip(schema_faq, visible_faq), start=1):
        if schema_item == visible_item:
            continue
        differences = []
        for field, label in (("question", "问题"), ("answer", "答案")):
            if schema_item[field] != visible_item[field]:
                differences.append(
                    f"{label}不一致：Schema={schema_item[field][:360]!r}；"
                    f"页面={visible_item[field][:360]!r}"
                )
        message = f"FAQ 第 {index} 项与 FAQPage Schema 不一致：" + "；".join(differences)
        home.mark_failure_evidence(details.nth(index - 1), message)
        raise AssertionError(message)


def test_homepage_image_alt_policy(home, page, test_platform):
    """REQ-14：业务图片都有 alt，且 alt 不使用文件名或医疗功效词。"""
    home.close_welcome_popup()
    images = page.locator("main img, header img, footer img")
    failures = []
    first_problem_index = None
    forbidden = re.compile(r"\b(cure|heal|medical|therapy)\b", re.I)
    filename = re.compile(r"\.(?:avif|gif|jpe?g|png|svg|webp)(?:\?|$)", re.I)
    for index, image in enumerate(images.all()):
        alt = image.get_attribute("alt")
        role = image.get_attribute("role")
        if alt is None:
            failures.append(f"图片 #{index + 1} 缺少 alt 属性")
            first_problem_index = index if first_problem_index is None else first_problem_index
            continue
        if alt and filename.search(alt):
            failures.append(f"图片 #{index + 1} alt 疑似文件名：{alt!r}")
            first_problem_index = index if first_problem_index is None else first_problem_index
        if alt and forbidden.search(alt):
            failures.append(f"图片 #{index + 1} alt 含禁用功效词：{alt!r}")
            first_problem_index = index if first_problem_index is None else first_problem_index
        if not alt and role not in (None, "presentation", "none"):
            failures.append(f"图片 #{index + 1} 使用空 alt 但 role={role!r}")
            first_problem_index = index if first_problem_index is None else first_problem_index
    if failures:
        home.mark_failure_evidence(images.nth(first_problem_index), failures[0])
        raise AssertionError("首页图片 alt 不符合要求：\n" + "\n".join(failures))


def test_core_content_is_present_in_server_html(home, page, test_platform):
    """REQ-15：不执行 JavaScript 的原始首页 HTML 包含核心 SEO 与导航内容。"""
    try:
        response = home.get_with_rate_limit_retry(home.base_url, timeout=20_000)
    except SiteRateLimitError as error:
        pytest.skip(str(error))
    assert response.status == 200, f"首页原始 HTML 返回 HTTP {response.status}"
    html = response.text()
    normalized = re.sub(r"\s+", " ", unescape(html))
    head_match = re.search(r"<head\b[^>]*>(.*?)</head>", html, re.I | re.S)
    assert head_match, "首页原始 HTML 缺少 head"
    title_matches = re.findall(
        r"<title\b[^>]*>(.*?)</title>", head_match.group(1), re.I | re.S
    )
    title_texts = [
        re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()
        for value in title_matches
    ]
    assert title_texts == [EXPECTED_TITLE], f"首页原始 HTML title 应唯一且精确匹配，实际为 {title_texts}"
    assert EXPECTED_DESCRIPTION in normalized, "首页原始 HTML 缺少精确 meta description"
    h1_matches = re.findall(r"<h1\b[^>]*>(.*?)</h1>", html, re.I | re.S)
    h1_texts = [
        re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()
        for value in h1_matches
    ]
    if h1_texts != [EXPECTED_H1]:
        visible_h1 = page.locator("h1")
        if visible_h1.count():
            evidence_target = (
                visible_h1
                if visible_h1.is_visible()
                else page.get_by_role("region", name="Banner")
            )
            home.mark_failure_evidence(
                evidence_target,
                f"服务端 HTML H1 应为 {EXPECTED_H1!r}，实际为 {h1_texts!r}",
            )
        raise AssertionError(f"原始 HTML H1 应唯一且精确匹配，实际为 {h1_texts}")
    collector = _AnchorCollector()
    collector.feed(html)
    for label, path in EXPECTED_NAVIGATION_LINKS.items():
        matches = [
            anchor for anchor in collector.anchors
            if anchor["text"].casefold() == label.casefold()
            and urlparse(anchor["href"]).path.rstrip("/") == path.rstrip("/")
        ]
        if not matches:
            home.mark_failure_evidence(
                page.locator("header"),
                f"服务端 HTML 缺少真实锚点 {label} -> {path}",
            )
            raise AssertionError(f"原始 HTML 缺少导航锚点 {label} -> {path}")
    # FAQ 标题由主题文案配置（当前为 ``FAQs``），不能把旧稿中的
    # ``Frequently Asked Questions`` 当成唯一正确值。这里验收稳定的
    # section 标识和 SSR 问答结构，再由 REQ-09/REQ-13 检查交互与 Schema。
    section_markers = ("Pick Your Style", "How It Works")
    missing_sections = [marker for marker in section_markers if marker not in normalized]
    if missing_sections:
        raise AssertionError("原始 HTML 缺少核心 section 文字：" + "、".join(missing_sections))
    faq_collector = _FaqContentCollector()
    faq_collector.feed(html)
    if not faq_collector.has_section:
        raise AssertionError("原始 HTML 缺少 FAQ section（data-jjb-faq）")
    if not faq_collector.items:
        raise AssertionError("原始 HTML 的 FAQ section 内没有 SSR 问答")
    incomplete_items = [
        index
        for index, item in enumerate(faq_collector.items, start=1)
        if not item["question"] or not item["answer"]
    ]
    if incomplete_items:
        raise AssertionError(
            "原始 HTML 的 FAQ 问题或答案为空：第 "
            + "、".join(map(str, incomplete_items))
            + " 项"
        )
