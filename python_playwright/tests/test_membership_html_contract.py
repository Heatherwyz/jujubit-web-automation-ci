"""会员付费墙服务端 HTML 契约层：只取一次原始 HTML，不起浏览器、不分端。

与 test_home_html_contract.py 同一模式：这层断言不依赖 JavaScript、视口和
登录态，结论确定——红了就是付费墙页面真改坏了。

复用 conftest 的 playwright_runtime（session 级）：自己调 sync_playwright()
会与浏览器层的 session fixture 冲突，报 "Sync API inside the asyncio loop"。
"""

from __future__ import annotations

import pytest

from python_playwright.membership_contract import (
    EXPECTED_MONTHLY_PRICES,
    KNOWN_PRICE_MISMATCH_TIERS,
    MEMBERSHIP_HTML_CONTRACTS,
    OBSERVED_ONLINE_PRICES,
    known_price_mismatch_reason,
)
from python_playwright.pages.home_page import SiteRateLimitError

PAYWALL_PATH = "/pages/vip-program"


@pytest.fixture(scope="module")
def paywall_server_html(playwright_runtime, request) -> str:
    """整层共用一次付费墙原始 HTML，避免每条契约各发一次请求。"""
    base_url = request.config.getoption("--base-url").rstrip("/")
    url = f"{base_url}{PAYWALL_PATH}"
    # api_request_context 只做 HTTP 请求，不启动浏览器，也不执行 JS。
    context = playwright_runtime.request.new_context(base_url=base_url)
    try:
        response = context.get(url, timeout=30_000)
        if response.status == 429:
            pytest.skip(
                "站点访问频控（HTTP 429）：未取得付费墙原始 HTML，"
                "本层契约未完成，不代表页面功能失败。"
            )
        assert response.status == 200, f"付费墙原始 HTML 返回 HTTP {response.status}"
        html = response.text()
    except SiteRateLimitError as error:  # pragma: no cover - 依赖线上频控
        pytest.skip(str(error))
    finally:
        context.dispose()
    assert html.strip(), "付费墙原始 HTML 为空，疑似白屏或被中间层拦截"
    return html


@pytest.mark.html_contract
@pytest.mark.membership
@pytest.mark.parametrize(
    ("contract_name", "check"),
    MEMBERSHIP_HTML_CONTRACTS,
    ids=[name for name, _check in MEMBERSHIP_HTML_CONTRACTS],
)
def test_membership_html_contract(paywall_server_html, contract_name, check):
    """逐条验收付费墙服务端 HTML 契约。

    这些是硬断言：检查函数内部已跳过 KNOWN_PRICE_MISMATCH_TIERS 里登记的档位，
    所以剩下的档位（当前是 Pro）必须真实通过。不要在这里加 xfail——那会把仍然
    有效的 Pro 断言一起藏掉。
    """
    problems = check(paywall_server_html)
    assert not problems, f"{contract_name} 不符合契约：" + "；".join(problems)


@pytest.mark.html_contract
@pytest.mark.membership
def test_membership_known_price_mismatch(paywall_server_html):
    """单独汇报已登记的会员价格不一致，记为未完成而不是通过。

    为什么单开一条：主契约里的 Pro 断言仍然有效且必须硬性通过，不能被 xfail
    连带藏掉。这一条只负责让 Premium 的不一致在报告里可见——它既不算通过
    （线上确实与确认值不符），也不算失败（已登记为已知问题，不是新回归）。

    价格对齐后从 KNOWN_PRICE_MISMATCH_TIERS 移除该档位，本条会转为通过。
    """
    if not KNOWN_PRICE_MISMATCH_TIERS:
        # 没有登记任何不一致：反向确认线上确实已与确认值对齐。
        for tier in EXPECTED_MONTHLY_PRICES:
            price = EXPECTED_MONTHLY_PRICES[tier]
            amount = price.lstrip("$")
            assert amount in paywall_server_html or price in paywall_server_html, (
                f"{tier} 月付价格 {price} 未出现——若线上已改价请更新确认值"
            )
        return

    # 有登记：把差异如实写进报告，并核对线上是否仍是记录中的那组值。
    for tier in sorted(KNOWN_PRICE_MISMATCH_TIERS):
        observed = OBSERVED_ONLINE_PRICES.get(tier, {})
        monthly = observed.get("monthly", "")
        if monthly and monthly.lstrip("$") not in paywall_server_html:
            # 线上价格又变了——已知问题的记录已过期，必须重新核对。
            raise AssertionError(
                f"{tier} 线上价格已不是记录中的 {monthly}，"
                "KNOWN_PRICE_MISMATCH_TIERS 与 OBSERVED_ONLINE_PRICES 需要更新"
            )
    pytest.xfail(known_price_mismatch_reason())
