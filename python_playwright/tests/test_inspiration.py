"""社区 Inspiration 自动化。

默认不进入每日回归：功能未全量放开时若每天执行，会把“未上线”误报成业务失败。
显式运行：

    .venv/bin/python run_all.py --inspiration-only --platform pc
"""

import re

import pytest
from playwright.sync_api import expect

from python_playwright.pages.inspiration_page import (
    InspirationNotLaunchedError,
    InspirationPage,
)


pytestmark = pytest.mark.inspiration


@pytest.fixture
def inspiration(home, page):
    """打开首页并返回 Inspiration 页面对象。"""
    return InspirationPage(page, home)


def _skip_if_not_launched(action) -> None:
    try:
        action()
    except InspirationNotLaunchedError as error:
        pytest.skip(str(error))


def test_inspiration_navigation_entry(inspiration, page, test_platform):
    """实验组可从当前端导航进入 SHOWCASE。"""
    _skip_if_not_launched(inspiration.open_from_navigation)
    expect(page.get_by_role("heading", name=re.compile(r"showcase", re.I))).to_be_visible()
    inspiration.assert_feed_loaded()
    inspiration.assert_no_backend_error()


def test_inspiration_tabs_come_from_server(inspiration, page, test_platform):
    """分区使用接口返回值，且不展示 campaign。"""
    _skip_if_not_launched(inspiration.open_from_navigation)
    tabs = inspiration.visible_tabs()
    assert tabs, "Inspiration 已进入，但没有可见分区"
    assert not any(re.search(r"campaign", tab["id"] + tab["name"], re.I) for tab in tabs)
    assert sum(tab["selected"] for tab in tabs) == 1, "必须有且只有一个默认分区"
    requests = inspiration.capture_feed_requests()
    assert any(inspiration.TAB_LIST_PATH in item["url"] for item in requests), (
        "进入 Inspiration 后没有请求分区接口"
    )


def test_inspiration_feed_pagination_appends(inspiration, page, test_platform):
    """首屏成功后接近底部才追加下一页，不覆盖已有作品。"""
    _skip_if_not_launched(inspiration.open_from_navigation)
    inspiration.assert_feed_loaded()
    before = inspiration.feed_cards().count()
    assert before > 0 or page.get_by_text(re.compile(r"暂无|nothing", re.I)).count() > 0
    if before == 0:
        pytest.skip("当前分区没有作品，分页留到有数据的分区复测。")
    page.mouse.wheel(0, 4000)
    page.wait_for_timeout(1000)
    after = inspiration.feed_cards().count()
    assert after >= before, "加载更多不能减少已展示的作品"


def test_inspiration_card_click_opens_detail_not_sku(inspiration, page, test_platform):
    """点击作品封面进入详情，不直接进入购买。"""
    _skip_if_not_launched(inspiration.open_from_navigation)
    card = inspiration.feed_cards().first
    expect(card).to_be_visible()
    inspiration.open_detail_from_card(card)
    expect(inspiration.detail_root()).to_be_visible()
    expect(inspiration.sku_root()).to_be_hidden()


def test_inspiration_cart_icon_does_not_open_detail(inspiration, page, test_platform):
    """购物车图标进入 SKU，不能同时打开详情。"""
    _skip_if_not_launched(inspiration.open_from_navigation)
    card = inspiration.feed_cards().first
    inspiration.add_to_cart_from_card(card)
    expect(inspiration.sku_root()).to_be_visible()
    assert inspiration.detail_root().count() == 0 or not inspiration.detail_root().is_visible()


def test_inspiration_price_format_matches_card_state(inspiration, test_platform):
    """可售作品价格使用 $X 或 From $X；不可售作品不显示价格。"""
    _skip_if_not_launched(inspiration.open_from_navigation)
    cards = inspiration.feed_cards()
    expect(cards.first).to_be_visible()
    sample = cards.nth(0)
    text = inspiration.card_price_text(sample)
    cart = sample.get_by_role("button", name=re.compile(r"cart|add", re.I))
    if cart.count() == 0:
        assert not re.search(r"\$\s*\d", text), "不可售作品不应显示价格"
        return
    assert re.search(r"(?:From\s+)?\$\s*\d+(?:\.\d{2})?", text), (
        f"可售作品价格格式不正确：{text}"
    )
