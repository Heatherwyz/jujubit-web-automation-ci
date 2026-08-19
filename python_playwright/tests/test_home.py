"""首页基础冒烟测试。

每个 ``test_`` 函数是一条可独立执行的测试场景；pytest 会通过共享的
``test_platform`` 参数将其分别在 PC 和 H5 视口下运行。
"""

from urllib.parse import urlparse

from playwright.sync_api import expect


def test_tc01_homepage_loads(home, page, test_platform):
    """TC-01：首页通过 HTTPS 正常打开，并渲染主内容区域。"""
    current = urlparse(page.url)
    assert current.scheme == "https"
    assert current.netloc == "jujubit.ai"
    assert current.path in ("", "/")
    expect(page.locator("main")).to_be_visible()


def test_tc02_page_has_no_error_markers(home, page, test_platform):
    """TC-02：标题和正文不应出现常见 404/服务异常标记。"""
    title = page.title().lower()
    body = page.locator("body").inner_text().lower()
    assert not any(marker in title for marker in ("404", "page not found", "internal server error"))
    assert "page not found" not in body
    assert "internal server error" not in body


def test_tc03_welcome_popup_can_close(home, page, test_platform):
    """TC-03：欢迎优惠弹窗出现时可关闭，且不遮挡首页内容。"""
    # 弹窗可能延迟出现；关闭后不能遮挡首页主内容。
    home.close_welcome_popup()
    expect(home.welcome_popup).to_be_hidden()
    assert not home.popup_is_blocking(), "优惠弹窗关闭后仍在遮挡页面操作"
    expect(page.locator("main")).to_be_visible()


def test_tc04_announcement_has_messages(home, test_platform):
    """TC-04：公告栏至少配置两条非空消息。"""
    home.close_welcome_popup()
    texts = home.announcement.locator("[data-announcement-slide]").all_text_contents()
    assert len(texts) >= 2
    assert all(text.strip() for text in texts)


def test_tc05_announcement_has_controls(home, page, test_platform):
    """TC-05：公告栏提供上一条和下一条的切换按钮。"""
    home.close_welcome_popup()
    expect(page.get_by_role("button", name="Previous announcement")).to_be_attached()
    expect(page.get_by_role("button", name="Next announcement")).to_be_attached()


def test_tc06_visible_logo_targets_home(home, test_platform):
    """TC-06：当前端可见的 Logo 指向首页根路径。"""
    home.close_welcome_popup()
    logo = home.visible_logo()
    expect(logo).to_have_count(1)
    expect(logo).to_have_attribute("href", "/")


def test_tc07_navigation_has_core_entries(home, test_platform):
    """TC-07：PC/H5 主导航均展示四个核心业务入口。"""
    home.close_welcome_popup()
    nav = home.navigation_root(test_platform)
    labels = ["Create", "Templates", "Categories", "How It Works"]
    if test_platform == "h5":
        actual = [text.strip() for text in nav.locator("a.jjb-mobile-nav__link").all_text_contents()]
        for label in labels:
            assert label in actual
    else:
        for label in labels:
            expect(nav.get_by_role("link", name=label, exact=True)).to_be_attached()


def test_tc08_navigation_links_are_internal(home, test_platform):
    """TC-08：主导航的实际链接为有效站内地址。"""
    home.close_welcome_popup()
    home.assert_internal_links(home.navigation_root(test_platform))


def test_tc09_hero_image_is_visible(home, page, test_platform):
    """TC-09：首屏 Hero Banner 和图片在当前端可见。"""
    home.close_welcome_popup()
    banner = page.get_by_role("region", name="Banner")
    expect(banner).to_be_visible()
    # 轮播会把非激活 slide 保留在 DOM 中，且 opacity: 0 在 Playwright 中仍可能
    # 被 ``:visible`` 识别。这里只验收当前激活 slide，避免把正常轮播误报成两张图。
    active_slide = banner.locator("[data-banner-slide].is-active")
    expect(active_slide).to_have_count(1)
    # 当前端只应显示 PC 或 H5 对应的一张媒体；这也能发现响应式样式错误地同时
    # 展示两张 Hero 图片的情况。
    platform_media = "mb" if test_platform == "h5" else "pc"
    active_image = active_slide.locator(
        f".jjb-banner__media-wrap--{platform_media}:visible > img.jjb-banner__media"
    )
    expect(active_image).to_have_count(1)
    assert active_image.evaluate(
        "element => element.complete && element.naturalWidth > 0"
    ), "当前 Hero 轮播项的图片未成功加载"


def test_tc10_hero_create_link_is_correct(home, page, test_platform):
    """TC-10：Hero CTA 使用主题实际配置的非空链接。"""
    home.close_welcome_popup()
    # 以主题当前配置的 Hero 链接为准，不绑定历史固定路径。
    links = page.get_by_role("region", name="Banner").locator("a[href]:visible")
    assert links.count() >= 1
    hrefs = links.evaluate_all("nodes => nodes.map(node => node.getAttribute('href'))")
    assert all(href and href != "#" for href in hrefs)


def test_tc11_style_section_has_entries(home, page, test_platform):
    """TC-11：Pick Your Style 至少提供五个创建入口。"""
    home.close_welcome_popup()
    expect(page.get_by_role("heading", name="Pick Your Style", exact=True)).to_be_visible()
    links = page.locator('main a[href*="/products/"]').filter(has_text="Create Now")
    assert links.count() >= 5


def test_tc12_how_it_works_has_four_steps(home, page, test_platform):
    """TC-12：How It Works 在不同端展示对应文案的四个步骤。"""
    home.close_welcome_popup()
    section = page.get_by_role("region", name="How It Works")
    steps = (
        ["Step 1 Pick Your Style", "Step 2 Upload Your Image", "Step 3 Preview in 3D", "Step 4 We Make & Ship It"]
        if test_platform == "h5"
        else ["01 Pick Your Style", "02 Upload Your Image", "03 Preview in 3D", "04 We Make & Ship It"]
    )
    for step in steps:
        expect(section.get_by_role("button", name=step)).to_be_attached()


def test_tc13_categories_has_five_items(home, page, test_platform):
    """TC-13：分类区域至少展示五项内容。"""
    home.close_welcome_popup()
    expect(page.get_by_role("heading", name="Categories", exact=True)).to_be_visible()
    assert page.locator("main article").count() >= 5


def test_tc14_trending_has_product_links(home, page, test_platform):
    """TC-14：Trending Products 至少包含五个商品链接。"""
    home.close_welcome_popup()
    expect(page.get_by_role("heading", name="Trending Products")).to_be_visible()
    assert page.locator('main a[href^="/products/"]').count() >= 5


def test_tc15_header_tools_exist(home, page, test_platform):
    """TC-15：头部搜索/菜单、登录和购物车入口存在。"""
    home.close_welcome_popup()
    if test_platform == "h5":
        expect(page.get_by_role("button", name="Site navigation", exact=True)).to_be_attached()
    else:
        expect(page.get_by_role("link", name="Search", exact=True)).to_be_attached()
    expect(page.get_by_role("link", name="Log in", exact=True)).to_be_attached()
    # 精确匹配 Cart，避免把购物车抽屉内的 Close cart 也算作头部入口。
    expect(page.get_by_role("button", name="Cart", exact=True)).to_be_attached()
