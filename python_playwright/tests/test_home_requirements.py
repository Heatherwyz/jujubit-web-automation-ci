"""首页 PRD 与技术文档的需求验收测试。

这里的 case 比基础冒烟层更关注可访问性、SEO、真实链接跳转、Footer 配置和
FAQ 交互等需求细节。每条同样由 pytest 自动拆分为 PC/H5 两端执行。
"""

import re
from html import unescape
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Error as PlaywrightError, expect


EXPECTED_TITLE = "JuJuBit | Custom Figurines, Crystal Bracelets & Art Toys"
EXPECTED_DESCRIPTION = (
    "JuJuBit makes custom figurines from your photo, crystal bracelets, and art toys. "
    "AI-assisted design, worldwide shipping. Turn your photo into a 3D collectible."
)
EXPECTED_H1 = "Create Your Own Custom Figurine From a Photo"


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
    expect(headings).to_have_text(EXPECTED_H1)


def test_logo_accessibility_text(home, test_platform):
    """REQ-02：Logo 图片或链接具有包含品牌名的无障碍文本。"""
    home.close_welcome_popup()
    logo_link = home.visible_logo()
    expect(logo_link).to_have_count(1)
    logo_image = logo_link.locator("img")
    if logo_image.count():
        expect(logo_image).to_have_attribute("alt", re.compile(r"JuJuBit", re.I))
    else:
        expect(logo_link).to_have_attribute("aria-label", "JuJuBit")


def test_hero_lcp_media_is_eager(home, page, test_platform):
    """REQ-03：首屏 Hero 媒体不懒加载，并预留尺寸以降低布局偏移。"""
    home.close_welcome_popup()
    hero_image = page.get_by_role("region", name="Banner").locator("img:visible").first
    expect(hero_image).to_be_visible()
    loading = hero_image.get_attribute("loading")
    if loading == "lazy":
        raise AssertionError(
            "需求预期：Hero 首屏图片立即加载；"
            "实际：图片使用 loading=lazy，可能延迟首屏最大内容绘制（LCP）"
        )
    has_dimensions = bool(hero_image.get_attribute("width") and hero_image.get_attribute("height"))
    has_aspect_ratio = hero_image.evaluate("el => getComputedStyle(el).aspectRatio !== 'auto'")
    assert has_dimensions or has_aspect_ratio


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
    failures = []
    for url, label in links.items():
        response = None
        last_error = None
        # 公网页面下载偶发超时；第二次使用更长时限，避免把已返回 200 的页面误报为坏链。
        for timeout in (8_000, 20_000):
            try:
                # 批量扫描也需限速；否则测试行为本身可能触发站点的 429 频控。
                home.pace_link_check_request()
                response = page.request.get(url, fail_on_status_code=False, timeout=timeout)
                break
            except PlaywrightError as error:
                last_error = error
        if response is None:
            summary = str(last_error).split("Call log:", 1)[0].strip()
            failures.append((label, url, f"请求异常：{summary}"))
            continue
        body = response.text()
        visible_text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", body))).strip()
        if response.status == 429:
            pytest.skip(
                "站点访问频控（HTTP 429）：链接扫描未完成，不代表首页链接或页面功能失败。"
            )
        if response.status == 404:
            failures.append((label, url, "HTTP 404"))
        elif response.status >= 500:
            failures.append((label, url, f"HTTP {response.status}"))
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

    # 主题脚本偶尔晚于 Footer 控件绑定；确认状态未变化时才重试一次点击。
    for attempt in range(2):
        switcher.click()
        try:
            expect(switcher).to_have_attribute("aria-expanded", "true", timeout=3_000)
            break
        except AssertionError:
            if attempt == 1:
                raise
            page.wait_for_timeout(400)
    options_panel = page.locator(f"#{panel_id}")
    expect(options_panel).to_be_visible()
    assert options_panel.locator("a[href]:visible").count() >= 2, (
        "本地化切换器展开后应至少提供两个地区或币种选项"
    )

    # 收起选项，验证控件可以重复操作且不会在用例结束时遮挡页面。
    switcher.click()
    expect(switcher).to_have_attribute("aria-expanded", "false", timeout=3_000)


def test_external_social_links_are_safe(home, page, test_platform):
    """REQ-06：Footer 外部社交链接含 noopener 与 noreferrer。"""
    home.close_welcome_popup()
    social_links = page.locator(
        'footer a[href*="instagram.com"], footer a[href*="youtube.com"], '
        'footer a[href*="x.com"], footer a[href*="tiktok.com"]'
    )
    assert social_links.count() == 4
    failures = []
    for link in social_links.all():
        rel_tokens = set((link.get_attribute("rel") or "").lower().split())
        missing = {"noopener", "noreferrer"} - rel_tokens
        if missing:
            failures.append((link, link.get_attribute("href"), rel_tokens, missing))
    if failures:
        first_link, href, rel_tokens, missing = failures[0]
        # 失败前滚动到实际社交图标，让录像同时包含页面证据与中文错误说明。
        first_link.evaluate(
            "element => element.scrollIntoView({ block: 'center', inline: 'nearest' })"
        )
        page.wait_for_timeout(800)
        actual_rel = " ".join(sorted(rel_tokens)) or "空"
        raise AssertionError(
            "需求预期：外部社交链接 rel 同时包含 noopener 和 noreferrer；"
            f"实际：{href} 的 rel=\"{actual_rel}\"，缺少 {'、'.join(sorted(missing))}"
        )


def test_homepage_links_are_real_anchors(home, page, test_platform):
    """REQ-07：核心导航与 CTA 都是带有效 href 的真实链接。"""
    home.close_welcome_popup()
    labels = ("Create", "Templates", "Categories", "How It Works")
    navigation = home.navigation_root(test_platform)
    for label in labels:
        links = navigation.locator("a[href]").filter(has_text=re.compile(rf"^\s*{re.escape(label)}\s*$"))
        assert links.count() >= 1, f"导航项不是可点击的真实链接：{label}"
        href = links.first.get_attribute("href")
        assert href and href != "#", f"导航项 href 无效：{label}"


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

        # 首页默认会展开第一条；先等它的收起动画完成，避免紧接着点击第二条时读到短暂的 open 属性。
        if first.get_attribute("open") is not None:
            first_summary.click()
            page.wait_for_function(
                """() => {
                    const detail = document.querySelector('main details');
                    const answer = detail?.querySelector('.jjb-faq__answer');
                    return detail && !detail.open && answer && answer.getBoundingClientRect().height < 2;
                }""",
                timeout=5_000,
            )

        second_summary.click()
        page.wait_for_function(
            """() => {
                const detail = document.querySelectorAll('main details')[1];
                const answer = detail?.querySelector('.jjb-faq__answer');
                return detail && detail.open && answer && answer.getBoundingClientRect().height > 2;
            }""",
            timeout=5_000,
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
