"""万圣节专题页自动化。

对应 2026-09-23 活动页用例中已经在
https://jujubit.ai/pages/halloween-special 上线、且不依赖后台配置的部分。
"""

import re

import pytest
from playwright.sync_api import expect

from python_playwright.pages.halloween_page import HalloweenPage


pytestmark = pytest.mark.halloween


@pytest.fixture
def halloween(home, page):
    """打开万圣节专题页。"""
    target = HalloweenPage(page, home)
    target.open()
    return target


def test_halloween_banner_and_creator_anchor(halloween, page, test_platform):
    """Banner 展示活动标题，并把主按钮锚到页内创作区。"""
    banner = halloween.banner()
    expect(banner).to_be_visible()
    expect(banner).to_contain_text(re.compile(r"Halloween Collection", re.I))
    button = banner.get_by_role("link", name=re.compile(r"Create Your Own", re.I))
    expect(button).to_have_attribute("href", "#jjb-page-canvas-section")
    # H5 弹窗可能在首屏观察结束后才出现，点击前再关闭一次。
    halloween.home.close_welcome_popup()
    button.click()
    expect(halloween.creator()).to_be_in_viewport()


def test_halloween_style_cards_have_unique_destinations(halloween, test_platform):
    """六张风格卡都有商品链接，且图片和按钮指向同一地址。"""
    cards = halloween.style_cards()
    expect(cards).to_have_count(6)
    hrefs = cards.evaluate_all(
        "(nodes) => nodes.map((node) => new URL(node.href).pathname)"
    )
    assert len(set(hrefs)) == 6, f"风格卡跳转地址重复：{hrefs}"
    assert all("/products/" in href for href in hrefs)
    for card in cards.all():
        expect(card.get_by_text(re.compile(r"EXPLORE NOW", re.I))).to_be_visible()
    expected_rows = 3 if test_platform == "h5" else 2
    assert halloween.row_count(cards) == expected_rows, "风格卡行数与当前端不一致"


def test_halloween_products_show_discount_and_two_columns_on_mobile(halloween, test_platform):
    """商品区展示折扣价，移动端固定两列。"""
    products = halloween.products()
    assert products.count() >= 8, "万圣节商品区商品数量异常偏少"
    sample = products.first.inner_text()
    assert re.search(r"\$\d+\.\d{2}", sample), f"商品缺少价格：{sample!r}"
    assert sample.lower().count("$") >= 2, f"折扣商品应同时有现价和原价：{sample!r}"
    if test_platform == "h5":
        assert halloween.row_count(products) * 2 >= products.count()
    else:
        assert halloween.row_count(products) >= 2
