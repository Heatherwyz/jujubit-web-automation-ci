"""0914 静态评论页契约。只取一次原始 HTML，不起浏览器。"""

import pytest

from python_playwright.reviews_contract import REVIEWS_PATH, reviews_contract_problems


@pytest.mark.html_contract
def test_reviews_page_server_html(playwright_runtime, request):
    """评论页必须返回约定标题、真实评论和评分，而不是错误页。"""
    base_url = request.config.getoption("--base-url").rstrip("/")
    context = playwright_runtime.request.new_context(base_url=base_url)
    try:
        response = context.get(REVIEWS_PATH, timeout=30_000)
        if response.status == 429:
            pytest.skip("站点访问频控（HTTP 429），评论页契约未完成。")
        assert response.status == 200, f"评论页返回 HTTP {response.status}"
        html = response.text()
    finally:
        context.dispose()
    problems = reviews_contract_problems(html)
    assert not problems, "；".join(problems)
