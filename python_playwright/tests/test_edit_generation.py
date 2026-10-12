"""0917 Edit 生成入口。

实验开启后，如果当前账号没有可复用的 Gallery 资产，就按现有创作流程
生成一次。生成完成后刷新页面，再验证 Edit 入口出现。
"""

import pytest

from python_playwright.pages.cart_page import CartPage
from python_playwright.pages.edit_generation_page import EditGenerationPage


pytestmark = pytest.mark.edit_generation


@pytest.fixture
def edit_generation(home, page):
    """开启实验并返回创作页对象。"""
    target = EditGenerationPage(page, home)
    target.enable_experiment()
    return target


@pytest.mark.membership_session
def test_edit_entry_visible_when_experiment_enabled(edit_generation):
    """已有或新生成的 Gallery 资产在实验开启并刷新后展示 Edit。"""
    edit_generation.open_gallery()
    edit_generation.home.close_welcome_popup()
    button = edit_generation.edit_button().first
    if button.count() == 0:
        creator = CartPage(
            edit_generation.page,
            edit_generation.home.base_url,
            edit_generation.home.config,
        )
        previous_total = creator.history_total()
        creator.open_create()
        creator.upload_image("")
        creator.generate_once()
        creator.wait_for_new_gallery_result(previous_total, timeout_seconds=600)
        edit_generation.enable_experiment()
        edit_generation.open_gallery()
        button = edit_generation.edit_button().first
    button.scroll_into_view_if_needed()
    button.wait_for(state="visible", timeout=15_000)
