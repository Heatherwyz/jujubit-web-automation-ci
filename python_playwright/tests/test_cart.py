"""购物车核心端到端主流程。"""

import pytest

from python_playwright.pages.cart_page import CartPage, SiteRateLimitError


@pytest.mark.cart_session
def test_cart_tc01_create_gallery_drawer_full_cart_checkout(
    page, request, test_platform
):
    """一次生成串联 Gallery、半屏/全屏购物车、99+ 与两次 Checkout。"""
    cart = CartPage(page, request.config.getoption("--base-url"), request.config)
    try:
        cart.clear_cart()
        # 1. 首页左上角 Create 可进入创作页面。
        cart.open_home()
        cart.open_creator_from_header()

        # 2. 上传一次并生成一次，History 必须增加，且本次结果同时具备 2D/3D。
        previous_history_total = cart.history_total()
        cart.upload_image(request.config.getoption("--pw-cart-image"))
        cart.generate_once()
        result = cart.wait_for_new_gallery_result(
            previous_history_total,
            request.config.getoption("--pw-generation-timeout"),
        )

        # 3. 当前 Gallery 模型加购后保持在创作页，并自动打开半屏购物车。
        gallery_url = page.url
        cart.add_current_model_to_cart()
        cart.assert_drawer_cart(quantity=1)

        # 同一 SKU 直接输入上限 100，验证 Checkout(100) 与 header 的 99+ 角标。
        cart.set_drawer_quantity(100)
        cart.assert_drawer_cart(quantity=100)

        # 4. 半屏购物车可进入 Checkout。
        cart.checkout_from_drawer()

        # 5. 返回刚才的 Gallery，点击右上角购物车按钮进入全屏购物车。
        cart.return_to_gallery(gallery_url, result)
        cart.open_full_cart_from_header()
        cart.assert_full_cart_page(quantity=100)

        # 6. 全屏购物车可进入 Checkout。
        cart.checkout_from_full_cart()
    except SiteRateLimitError as error:
        pytest.skip(str(error))
    finally:
        cart.clear_cart(ignore_errors=True)
