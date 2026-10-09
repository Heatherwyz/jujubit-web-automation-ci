"""0702 Contact 页面匿名用户标识。

标识由浏览器运行时生成，服务端 HTML 只有提示文案。用例只验证展示，
不记录或上报具体标识。
"""

import re

import pytest
from playwright.sync_api import expect

from python_playwright.contact_contract import CONTACT_PATH, UID_INSTRUCTION


@pytest.mark.contact
def test_contact_page_exposes_anonymous_uid(home, page, test_platform):
    """匿名访问 Contact 页面时展示可复制标识。"""
    home.open(CONTACT_PATH)
    home.close_welcome_popup()
    instruction = page.get_by_text(UID_INSTRUCTION)
    expect(instruction).to_be_visible()
    text = instruction.locator("xpath=ancestor::*[contains(., ':')][1]").inner_text()
    assert re.search(r":\s*\S{8,}", text), "Contact 页面未展示匿名用户标识"
