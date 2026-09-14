"""首页服务端 HTML 契约层：只取一次原始 HTML，不起浏览器、不分 PC/H5。

分层理由：这一层的断言不依赖 JavaScript、视口、登录态和渲染时序，所以结论是
确定的——红了就是站点或主题真的改坏了。它不参与 ``test_platform`` 参数化（同一份
HTML 在两端完全相同，跑两遍只是多一次请求），也不创建 BrowserContext。

需要真实点击、可见性判断和交互的验收留在 ``test_home_requirements.py``。那一层
会受频控、人机验证和主题异步初始化影响，失败时要先排除环境因素。

契约的具体判定在 ``python_playwright/home_contract.py``，已由 tests/ 下的离线单测
逐条覆盖，因此本层只负责取真实 HTML 并汇报差异。
"""

from __future__ import annotations

import pytest

from python_playwright.home_contract import HOME_HTML_CONTRACTS
from python_playwright.pages.home_page import SiteRateLimitError


@pytest.fixture(scope="module")
def home_server_html(request) -> str:
    """整层共用一次首页原始 HTML，避免每条契约各发一次请求放大频控。"""
    playwright = pytest.importorskip("playwright.sync_api")
    base_url = request.config.getoption("--base-url").rstrip("/")
    with playwright.sync_playwright() as driver:
        # api_request_context 只做 HTTP 请求，不启动浏览器进程，也不执行 JS。
        context = driver.request.new_context(base_url=base_url)
        try:
            response = context.get(base_url, timeout=30_000)
            if response.status == 429:
                pytest.skip(
                    "站点访问频控（HTTP 429）：未取得首页原始 HTML，"
                    "本层契约未完成，不代表页面功能失败。"
                )
            assert response.status == 200, (
                f"首页原始 HTML 返回 HTTP {response.status}"
            )
            html = response.text()
        except SiteRateLimitError as error:  # pragma: no cover - 依赖线上频控
            pytest.skip(str(error))
        finally:
            context.dispose()
    assert html.strip(), "首页原始 HTML 为空，疑似白屏或被中间层拦截"
    return html


@pytest.mark.html_contract
@pytest.mark.parametrize(
    ("contract_name", "check"),
    HOME_HTML_CONTRACTS,
    ids=[name for name, _check in HOME_HTML_CONTRACTS],
)
def test_home_server_html_contract(home_server_html, contract_name, check):
    """逐条验收服务端 HTML 契约，一条失败不影响其余契约继续给出结论。"""
    problems = check(home_server_html)
    assert not problems, f"{contract_name} 不符合契约：" + "；".join(problems)
