"""0917 Edit 生成入口。

只验证确认过的实验开关能够展示入口，不点击 Edit，也不创建新生成任务。
"""

import pytest

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
    """已有 Gallery 资产在 edit_generation.enable=true 时展示 Edit。"""
    edit_generation.open_gallery()
    edit_generation.edit_button().first.wait_for(state="visible", timeout=15_000)
