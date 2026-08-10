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
EXPECTED_H1 = "Create a Custom Figurine From Your Photo"
EXPECTED_LOGO_ALT = "JuJuBit - Custom 3D Figurines"
EXPECTED_NAVIGATION_LINKS = {
    "Templates": "/collections/templates-create-your-own",
    "Gallery": "/pages/gallery",
    "How It Works": "/pages/how-it-works",
}
EXPECTED_CATEGORY_LINKS = {
    "Custom Figurines": "/collections/custom-figurines",
    "Crystal Bracelets": "/collections/crystal-bracelets",
    "Art Toys": "/collections/art-toy",
    "Custom Keycaps": "/collections/keycaps",
    "Custom Keychains": "/collections/custom-keychains",
    "Acrylic Boards": "/collections/acrylic-standees",
}
# REQ-06 是安全属性验收：所有已确认社交平台都必须独立检查，不能因为
# 第一个平台失败，就漏掉其他平台的同类问题。
EXPECTED_SOCIAL_PLATFORMS = (
    ("Instagram", "JuJuBit on Instagram", "www.instagram.com", "/thisisjujubit_"),
    ("TikTok", "JuJuBit on TikTok", "www.tiktok.com", "/@jujubit_official"),
    ("YouTube", "JuJuBit on YouTube", "www.youtube.com", "/@thisisjujubit"),
    ("X", "JuJuBit on X", "x.com", "/thisisjujubit"),
    ("Snapchat", "JuJuBit on Snapchat", "www.snapchat.com", "/add/thisisjujubit"),
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
    hero_image = page.get_by_role("region", name="Banner").locator("img:visible").first
    expect(hero_image).to_be_visible()
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
    """REQ-04：扫描首页当前配置的站内链接，排除错误页和疑似白屏。"""
    home.close_welcome_popup()
    expect(home.welcome_popup).to_be_hidden()
    configured = page.locator(
        '[role="region"][aria-label="Announcement bar"] a[href], '
        'header a[href], main a[href], footer a[href]'
    ).evaluate_all(
        """nodes => nodes.map(node => ({
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
        # Shopify 系统页在未登录或缺少查询条件时可能返回空壳，不纳入首页业务链接检查。
        if parsed.path in {"/account", "/cart", "/search", "/checkout"}:
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
        if status == 404:
            failures.append((label, url, "HTTP 404"))
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
    """REQ-06：Footer 五个平台的地址、名称和安全属性均符合文案基准。"""
    home.close_welcome_popup()
    social_links = page.locator("footer a[href]")
    # 一次读取 Footer 链接，随后按平台分别校验，避免第一个失败掩盖后续平台的结果。
    items = social_links.evaluate_all(
        r"""nodes => nodes.map((node, index) => ({
            index,
            href: node.href,
            rel: node.getAttribute('rel') || '',
            ariaLabel: node.getAttribute('aria-label') || '',
        }))"""
    )
    failures = []
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
        parsed = urlparse(item["href"])
        rel_tokens = set(item["rel"].lower().split())
        missing = {"noopener", "noreferrer"} - rel_tokens
        mismatches = []
        if parsed.path.rstrip("/") != expected_path.rstrip("/"):
            mismatches.append(f"路径应为 {expected_path}，实际为 {parsed.path}")
        if item["ariaLabel"] != aria_label:
            mismatches.append(
                f"aria-label 应为 {aria_label!r}，实际为 {item['ariaLabel']!r}"
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
                    "link": social_links.nth(item["index"]),
                }
            )
    if failures:
        first_failure = failures[0]
        first_link = first_failure["link"]
        # 失败前给首个异常图标加红框；错误文本仍会完整列出五个平台的检查结果。
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
            "需求预期：Footer 五个平台的 URL、aria-label 和 rel 均符合文案基准；\n"
            "实际异常（五个平台均已检查）：\n" + "\n".join(details)
        )


def test_homepage_links_are_real_anchors(home, page, test_platform):
    """REQ-07：核心导航与 CTA 都是带有效 href 的真实链接。"""
    home.close_welcome_popup()
    # Categories 是下拉容器，不要求自身有落地页；其六个子项由 REQ-11 校验。
    labels = ("Create", "Templates", "Gallery", "How It Works")
    navigation = home.navigation_root(test_platform)
    for label in labels:
        links = navigation.locator("a[href]").filter(has_text=re.compile(rf"^\s*{re.escape(label)}\s*$"))
        if links.count() < 1:
            home.mark_failure_evidence(navigation, f"导航缺少可点击的真实链接：{label}")
            raise AssertionError(f"导航项不是可点击的真实链接：{label}")
        href = links.first.get_attribute("href")
        if not href or href == "#":
            home.mark_failure_evidence(links.first, f"导航项 {label} 的 href={href!r}")
            raise AssertionError(f"导航项 href 无效：{label}")


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
    """REQ-11：Header 主入口和六个品类使用需求指定的 URL。"""
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
    expected = {**EXPECTED_NAVIGATION_LINKS, **EXPECTED_CATEGORY_LINKS}
    failures = []
    first_problem_index = None
    for label, expected_path in expected.items():
        matches = [item for item in items if item["text"].casefold() == label.casefold()]
        if not matches:
            failures.append(f"缺少导航链接 {label!r}")
            continue
        actual_paths = {item["path"] for item in matches}
        if expected_path not in actual_paths:
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


def test_category_content_has_required_default_group(home, page, test_platform):
    """REQ-12：Category 包含六个默认品类且不展示 Pillow Cases。"""
    home.close_welcome_popup()
    category_heading = page.get_by_role("heading", name="Categories", exact=True)
    expect(category_heading).to_be_visible()
    # 只检查 Categories 所属的 Shopify section，避免其他模块的同路径链接造成假通过。
    category_section = category_heading.locator(
        "xpath=ancestor::*[starts-with(@id, 'shopify-section-')][1]"
    )
    expect(category_section).to_have_count(1)
    items = category_section.locator("a[href]").evaluate_all(
        r"""nodes => nodes.map(node => ({
            text: (node.textContent || '').trim().replace(/\s+/g, ' '),
            path: new URL(node.href, location.href).pathname.replace(/\/$/, '') || '/',
        }))"""
    )
    paths = {item["path"] for item in items}
    missing = [
        f"{label} ({path})"
        for label, path in EXPECTED_CATEGORY_LINKS.items()
        if path not in paths
    ]
    if missing:
        home.mark_failure_evidence(
            category_section,
            "Category 缺少默认品类入口：" + "、".join(missing),
        )
        raise AssertionError("Category 缺少默认品类入口：" + "、".join(missing))
    visible_text = category_section.inner_text().casefold()
    if "pillow cases" in visible_text:
        home.mark_failure_evidence(category_section, "Category 区域展示了 Pillow Cases")
        raise AssertionError("首页展示组不应出现 Pillow Cases")


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
    section_markers = ("Pick Your Style", "How It Works", "Frequently Asked Questions")
    missing_sections = [marker for marker in section_markers if marker not in normalized]
    assert not missing_sections, "原始 HTML 缺少核心 section 文字：" + "、".join(missing_sections)
