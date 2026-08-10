"""购物车 UI 优化的 15 条独立端到端自动化用例。"""

from contextlib import contextmanager
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from python_playwright.pages.cart_page import (
    CartPage,
    CartTestDataUnavailable,
    SiteRateLimitError,
)


@contextmanager
def _isolated_cart(page, request):
    """为每条 case 清空购物车，并把环境型前置不足转换为跳过。"""
    cart = CartPage(page, request.config.getoption("--base-url"), request.config)
    try:
        cart.clear_cart()
        yield cart
    except (SiteRateLimitError, CartTestDataUnavailable) as error:
        pytest.skip(str(error))
    finally:
        cart.clear_cart(ignore_errors=True)


def _open_creator(cart: CartPage) -> None:
    cart.open_home()
    cart.open_creator_from_header()


def _open_existing_gallery(cart: CartPage):
    """进入创作页并打开账号最新一条可购买的 Gallery 资产。"""
    _open_creator(cart)
    return cart.open_existing_gallery_result()


def _add_existing_gallery_model(cart: CartPage):
    result = _open_existing_gallery(cart)
    gallery_url = cart.page.url
    cart.add_current_model_to_cart()
    return result, gallery_url


def _fulfill_server_error(route) -> None:
    route.fulfill(
        status=500,
        content_type="application/json",
        body='{"message":"simulated cart failure"}',
    )


@pytest.mark.cart_session
def test_cart_tc01_header_create_opens_creator(page, request, test_platform):
    """CART-01：首页 Header Create 可进入真正可操作的创作页。"""
    with _isolated_cart(page, request) as cart:
        _open_creator(cart)
        cart.assert_creator_controls()


@pytest.mark.cart_session
def test_cart_tc02_upload_result_has_2d_and_3d(page, request, test_platform):
    """CART-02：唯一创建生成任务的 case，校验本次 2D/3D 结果。"""
    with _isolated_cart(page, request) as cart:
        _open_creator(cart)
        previous_history_total = cart.history_total()
        cart.upload_image(request.config.getoption("--pw-cart-image"))
        cart.generate_once()
        result = cart.wait_for_new_gallery_result(
            previous_history_total,
            request.config.getoption("--pw-generation-timeout"),
        )
        assert result.history_total > previous_history_total
        assert result.image_url


@pytest.mark.cart_session
def test_cart_tc03_gallery_add_opens_drawer(page, request, test_platform):
    """CART-03：Gallery 加购成功后留在创作页并自动打开半屏购物车。"""
    with _isolated_cart(page, request) as cart:
        _add_existing_gallery_model(cart)
        assert urlparse(page.url).path == cart.CREATOR_PATH
        cart.assert_drawer_cart(quantity=1)
        cart.assert_drawer_layout(test_platform)
        assert cart.cart_json()["item_count"] == 1


@pytest.mark.cart_session
def test_cart_tc04_drawer_checkout_opens_checkout(page, request, test_platform):
    """CART-04：半屏购物车可直接进入 Checkout。"""
    with _isolated_cart(page, request) as cart:
        _add_existing_gallery_model(cart)
        snapshot = cart.drawer_snapshot()
        cart.checkout_from_drawer()
        cart.assert_checkout_summary(snapshot)


@pytest.mark.cart_session
def test_cart_tc05_header_opens_full_cart(page, request, test_platform):
    """CART-05：Gallery Header Cart 可打开数据一致的全屏购物车。"""
    with _isolated_cart(page, request) as cart:
        _add_existing_gallery_model(cart)
        drawer_snapshot = cart.drawer_snapshot()
        cart.close_drawer()
        cart.open_full_cart_from_header(expected_quantity=1)
        cart.assert_full_cart_page(quantity=1)
        cart.assert_full_cart_matches(drawer_snapshot)


@pytest.mark.cart_session
def test_cart_tc06_full_cart_checkout_opens_checkout(page, request, test_platform):
    """CART-06：全屏购物车可进入 Checkout。"""
    with _isolated_cart(page, request) as cart:
        _add_existing_gallery_model(cart)
        cart.close_drawer()
        cart.open_full_cart_from_header(expected_quantity=1)
        snapshot = cart.full_cart_snapshot()
        cart.checkout_from_full_cart()
        cart.assert_checkout_summary(snapshot)


@pytest.mark.cart_session
def test_cart_tc07_header_badge_boundaries(page, request, test_platform):
    """CART-07：Header 角标覆盖空车、1、99 和 100（99+）边界。"""
    with _isolated_cart(page, request) as cart:
        _open_existing_gallery(cart)
        cart.assert_header_badge(0)
        cart.add_current_model_to_cart()
        cart.assert_drawer_cart(quantity=1)
        cart.set_drawer_quantity(99)
        cart.assert_drawer_cart(quantity=99)
        cart.set_drawer_quantity(100)
        cart.assert_drawer_cart(quantity=100)


@pytest.mark.cart_session
def test_cart_tc08_drawer_and_full_cart_content(page, request, test_platform):
    """CART-08：半屏和全屏购物车核心内容完整且数据一致。"""
    with _isolated_cart(page, request) as cart:
        _add_existing_gallery_model(cart)
        cart.assert_drawer_cart(quantity=1)
        cart.assert_drawer_layout(test_platform)
        cart.assert_drawer_discount_fields()
        drawer_snapshot = cart.drawer_snapshot()
        cart.close_drawer()
        cart.open_full_cart_from_header(expected_quantity=1)
        cart.assert_full_cart_content(quantity=1)
        cart.assert_full_cart_matches(drawer_snapshot)


@pytest.mark.cart_session
def test_cart_tc09_free_shipping_boundaries(page, request, test_platform):
    """CART-09：包邮提示覆盖 $98.99、$99.00、$99.01 三个边界。"""
    with _isolated_cart(page, request) as cart:
        _add_existing_gallery_model(cart)
        for total_cents in (9_899, 9_900, 9_901):
            cart.set_shipping_boundary_total(total_cents)
            cart.assert_shipping_boundary(total_cents)


@pytest.mark.cart_session
def test_cart_tc10_quantity_buttons_update_totals(page, request, test_platform):
    """CART-10：数量加减会联动角标、金额、包邮提示和 Checkout 件数。"""
    with _isolated_cart(page, request) as cart:
        _add_existing_gallery_model(cart)
        initial = cart.drawer_snapshot()
        cart.assert_drawer_quantity_control(quantity=1)

        cart.click_drawer_quantity("increase", expected_quantity=2)
        increased = cart.drawer_snapshot()
        cart.assert_drawer_quantity_control(quantity=2)
        assert increased.subtotal != initial.subtotal, "数量加到 2 后 Subtotal 未更新"

        cart.click_drawer_quantity("decrease", expected_quantity=1)
        restored = cart.drawer_snapshot()
        cart.assert_drawer_quantity_control(quantity=1)
        assert restored.subtotal == initial.subtotal, "数量减回 1 后 Subtotal 未恢复"


@pytest.mark.cart_session
def test_cart_tc11_delete_last_item_shows_empty_cart(page, request, test_platform):
    """CART-11：删除最后一件商品后展示最终确认的空购物车状态。"""
    with _isolated_cart(page, request) as cart:
        _add_existing_gallery_model(cart)
        cart.assert_drawer_quantity_control(quantity=1)
        cart.click_drawer_quantity("decrease", expected_quantity=0)
        cart.assert_empty_drawer()
        assert cart.cart_json()["item_count"] == 0


@pytest.mark.cart_session
def test_cart_tc12_quantity_input_caps_at_100(page, request, test_platform):
    """CART-12：手工输入 101 时回正为上限 100，并显示 99+。"""
    with _isolated_cart(page, request) as cart:
        _add_existing_gallery_model(cart)
        cart.set_drawer_quantity(101, expected_quantity=100)
        cart.assert_drawer_cart(quantity=100)
        cart.assert_drawer_quantity_control(quantity=100)
        expect(cart.drawer.locator(".ccd-qty-num")).to_have_attribute(
            "inputmode", "numeric"
        )
        assert cart.cart_json()["item_count"] == 100


@pytest.mark.cart_session
def test_cart_tc13_views_stay_consistent_and_full_cart_closes(
    page, request, test_platform
):
    """CART-13：半屏/全屏数据一致，全屏 Close 返回原 Gallery 且商品保留。"""
    with _isolated_cart(page, request) as cart:
        _, gallery_url = _add_existing_gallery_model(cart)
        cart.set_drawer_quantity(2)
        drawer_snapshot = cart.drawer_snapshot()
        cart.close_drawer()
        cart.open_full_cart_from_header(expected_quantity=2)
        cart.assert_full_cart_matches(drawer_snapshot)
        cart.close_full_cart(expected_url=gallery_url)
        assert urlparse(page.url).path == urlparse(gallery_url).path
        assert cart.cart_json()["item_count"] == 2


@pytest.mark.cart_session
def test_cart_tc14_checkout_summary_matches_cart(page, request, test_platform):
    """CART-14：Checkout 订单摘要与进入前的购物车商品、数量和金额一致。"""
    with _isolated_cart(page, request) as cart:
        _add_existing_gallery_model(cart)
        cart.set_drawer_quantity(2)
        snapshot = cart.drawer_snapshot()
        cart.checkout_from_drawer()
        cart.assert_checkout_summary(snapshot)


@pytest.mark.cart_session
def test_cart_tc15_failures_do_not_create_false_cart_state(
    page, request, test_platform
):
    """CART-15：add/change 返回 500 时不产生假状态、非法值或白屏。"""
    with _isolated_cart(page, request) as cart:
        _open_existing_gallery(cart)

        page.route("**/cart/add.js*", _fulfill_server_error)
        try:
            with pytest.raises(AssertionError, match=r"Gallery 加购接口失败：HTTP 500"):
                cart.add_current_model_to_cart()
        finally:
            page.unroute("**/cart/add.js*", _fulfill_server_error)
        assert cart.cart_json()["item_count"] == 0, "add 失败后服务端出现假商品"
        cart.assert_page_integrity(expected_cart_quantity=0)

        cart.add_current_model_to_cart()
        before_change = cart.cart_json()
        assert before_change["item_count"] == 1
        page.route("**/cart/change.js*", _fulfill_server_error)
        try:
            with pytest.raises(AssertionError, match=r"修改购物车数量失败：HTTP 500"):
                cart.set_drawer_quantity(2)
        finally:
            page.unroute("**/cart/change.js*", _fulfill_server_error)

        after_change = cart.cart_json()
        assert after_change["item_count"] == before_change["item_count"]
        assert [item["quantity"] for item in after_change["items"]] == [
            item["quantity"] for item in before_change["items"]
        ], "change 失败后服务端数量被错误修改"
        cart.assert_page_integrity(
            expected_cart_quantity=before_change["item_count"]
        )
