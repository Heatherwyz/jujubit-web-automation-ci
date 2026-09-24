"""pytest + Playwright 共享夹具和中文报告生成逻辑。

pytest 会在运行每条 ``test_...`` 用例前自动调用本文件中的夹具：创建浏览器、
设置 PC/H5 视口和页面上下文；运行结束后再把结果、截图和失败录像写进 HTML 报告。
"""

from datetime import datetime
import json
from pathlib import Path
import re
import socket
import time
from html import escape

import pytest
from playwright.sync_api import sync_playwright

from python_playwright.report_summary import (
    RESULT_LABELS,
    build_summary_html,
)
from python_playwright.cart_cases import (
    CART_CASES_BY_FUNCTION,
    DAILY_H5_CASE_FUNCTIONS,
)
from python_playwright.membership_cases import MEMBERSHIP_CASE_TITLES
from python_playwright.pages.home_page import (
    RATE_LIMIT_DETAIL_PATTERN,
    HomePage,
    SiteRateLimitError,
)
from python_playwright.pages.membership_page import MembershipNotLaunchedError


ROOT = Path(__file__).resolve().parents[2]
VIEWPORTS = {
    "pc": {"width": 1440, "height": 900},
    "h5": {"width": 390, "height": 844},
}
CASE_TITLES = {
    "test_tc01_homepage_loads": "TC-01: 首页可以正常打开",
    "test_tc02_page_has_no_error_markers": "TC-02: 页面标题和正文没有错误页标记",
    "test_tc03_welcome_popup_can_close": "TC-03: 欢迎优惠弹窗可以关闭",
    "test_tc04_announcement_has_messages": "TC-04: 公告栏至少包含两条有效消息",
    "test_tc05_announcement_has_controls": "TC-05: 公告栏包含前后切换按钮",
    "test_tc06_visible_logo_targets_home": "TC-06: 当前端可见 Logo 指向首页",
    "test_tc07_navigation_has_core_entries": "TC-07: 主导航包含核心入口",
    "test_tc08_navigation_links_are_internal": "TC-08: 主导航链接均为站内地址",
    "test_tc09_hero_image_is_visible": "TC-09: Hero Banner 图片可见",
    "test_tc10_hero_create_link_is_correct": "TC-10: Hero 创建入口指向定制商品",
    "test_tc11_style_section_has_entries": "TC-11: Pick Your Style 区域包含样式入口",
    "test_tc12_how_it_works_has_four_steps": "TC-12: How It Works 展示四个制作步骤",
    "test_tc13_categories_has_five_items": "TC-13: Categories 区域至少展示五个分类",
    "test_tc14_trending_has_product_links": "TC-14: Trending Products 包含有效商品链接",
    "test_tc15_header_tools_exist": "TC-15: 头部搜索、登录和购物车入口存在",
    "test_homepage_seo_metadata": "REQ-01: 首页 SEO 标题、描述和唯一 H1 符合需求",
    "test_logo_accessibility_text": "REQ-02: Logo 具有正确的品牌无障碍名称",
    "test_hero_lcp_media_is_eager": "REQ-03: Hero 首屏图片不使用懒加载",
    "test_configured_internal_links_are_available": "REQ-04: 首页普通站内业务链接均可访问且不是白屏",
    "test_customer_account_login_entry_is_usable": "REQ-04A: 当前可见 Log in 入口可正常打开",
    "test_configured_navigation_and_hero_links_can_open": "REQ-04B: 首页配置的导航与 Hero 链接可真实打开",
    "test_footer_locale_switcher_is_available": "REQ-05: Footer 地区与币种切换器可见且可展开",
    "test_external_social_links_are_safe": "REQ-06: Footer 当前社交平台地址、名称与安全属性正确",
    "test_homepage_links_are_real_anchors": "REQ-07: 当前一级导航均使用有效真实链接",
    "test_social_videos_have_inline_playback_attributes": "REQ-08: 社交视频具备移动端内联静音循环属性",
    "test_faq_semantics_and_single_expansion": "REQ-09: FAQ 语义结构正确且只展开一项",
    "test_hero_heading_hierarchy": "REQ-10: Hero 标题使用 H2 层级",
    "test_navigation_and_category_urls_match_requirements": "REQ-11: Header 与品类导航 URL 符合需求",
    "test_homepage_json_ld_is_valid_and_matches_faq": "REQ-13: JSON-LD 可解析且 FAQ 与页面同源",
    "test_homepage_image_alt_policy": "REQ-14: 首页图片 alt 符合 SEO 与合规要求",
    "test_core_content_is_present_in_server_html": "REQ-15: 原始 HTML 包含核心 SEO、导航与区块内容",
    "test_home_server_html_contract": "HTML 契约",
    "test_ci_smoke_generate_add_and_checkout": (
        "CART-SMOKE: 单一登录上下文完成生成、加购、全屏购物车与 Checkout"
    ),
    "test_membership_html_contract": "会员 HTML 契约",
    "test_membership_known_price_mismatch": (
        "会员 HTML 契约：已知价格不一致（Premium 线上与确认值不符）"
    ),
    **{
        function_name: case.report_title
        for function_name, case in CART_CASES_BY_FUNCTION.items()
    },
    # 会员用例标题由 membership_cases.py 统一维护，新增用例只改那一处。
    **MEMBERSHIP_CASE_TITLES,
}

class SiteRequestPacer:
    """串行控制首页导航频率，避免连续 case 触发线上 429 限流。"""

    def __init__(self, interval: float):
        self.interval = max(0.0, interval)
        self.next_allowed_at = 0.0

    def wait(self) -> None:
        """等待到下一次允许访问首页的时刻，并为下一次请求预留间隔。"""
        now = time.monotonic()
        if now < self.next_allowed_at:
            time.sleep(self.next_allowed_at - now)
        self.next_allowed_at = time.monotonic() + self.interval


def pytest_generate_tests(metafunc):
    """把同一个业务 case 参数化为 PC、H5 两个独立执行记录。"""
    if "test_platform" not in metafunc.fixturenames:
        return
    selected = metafunc.config.getoption("--pw-platform")
    # 同一用例在 PC 与 H5 独立执行，保证响应式问题可单独定位。
    platforms = ("pc", "h5") if selected == "all" else (selected,)
    metafunc.parametrize("test_platform", platforms, ids=platforms, scope="function")


def _item_function_name(item) -> str:
    """返回 pytest item 对应的原始函数名，不依赖参数化后的显示名称。"""
    return getattr(item, "originalname", None) or item.name.split("[")[0]


def _item_platform(item) -> str:
    """读取参数化平台；没有平台参数的测试返回空字符串。"""
    callspec = getattr(item, "callspec", None)
    params = getattr(callspec, "params", {}) if callspec is not None else {}
    return str(params.get("test_platform", ""))


def _daily_cart_item_is_selected(item) -> bool:
    """判断每日购物车分层是否保留一条已参数化的购物车记录。

    每日套件固定保留 PC 的 15 条逻辑用例，H5 只保留结构化清单中的 6
    条关键用例。判断依据是 ``CART_CASES`` 的函数映射和 callspec 平台值，
    不解析 nodeid，也不依赖容易随函数改名失效的 ``-k`` 字符串。
    """
    function_name = _item_function_name(item)
    if function_name not in CART_CASES_BY_FUNCTION:
        # Smoke 或首页等非 15 条逻辑购物车 case 由 -m 负责选择，不在这里误删。
        return True
    platform = _item_platform(item)
    if platform == "pc":
        return True
    if platform == "h5":
        return function_name in DAILY_H5_CASE_FUNCTIONS
    # 未知平台不应被每日套件默默执行；保守地排除并在收集摘要中体现。
    return False


def _suite_display_name(config) -> str:
    """返回报告/终端使用的中文套件名称。"""
    suite = config.getoption("--pw-cart-suite")
    return {
        "none": "默认回归",
        "smoke": "购物车 Smoke（单一主链路）",
        "daily": "购物车每日分层（PC 15 + H5 关键 6）",
        "full": "购物车完整回归（PC 15 + H5 15）",
    }.get(suite, suite)


def pytest_collection_modifyitems(config, items):
    """按结构化平台/Case 清单筛选每日购物车记录。

    ``pytest_generate_tests`` 先为每条 case 生成 PC/H5 参数；本 hook 再依据
    ``--pw-cart-suite daily`` 删除不在每日层的 H5 记录。这样 pytest 收集结果
    直接就是 21 条（而不是执行 30 条后再把 9 条伪装成跳过），同时保留
    ``--pw-platform pc/h5`` 的显式平台约束。
    """
    suite = config.getoption("--pw-cart-suite")
    config._jujubit_suite_name = _suite_display_name(config)
    config._jujubit_daily_deselected = 0
    if suite != "daily":
        return

    kept = []
    deselected = []
    for item in items:
        # 只对真实 15 条结构化购物车 case 做每日分层；首页和 Smoke 由 -m
        # 表达式控制，避免改变普通首页回归及兼容入口的语义。
        if (
            _item_function_name(item) in CART_CASES_BY_FUNCTION
            and not item.get_closest_marker("cart_smoke")
            and not _daily_cart_item_is_selected(item)
        ):
            deselected.append(item)
        else:
            kept.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = kept
    # 最终收集数要等 -m/-k 等其它 pytest hook 完成后才能准确得到；这里仅记录
    # 本 hook 实际排除的 9 条 H5 深度用例，pytest_collection_finish 再写最终数。
    config._jujubit_daily_deselected = len(deselected)


def pytest_collection_finish(session):
    """记录 pytest 最终将执行的条数，供 HTML 和终端准确展示执行范围。"""
    config = session.config
    config._jujubit_suite_name = getattr(
        config, "_jujubit_suite_name", _suite_display_name(config)
    )
    config._jujubit_collection_counts = {
        "suite": config.getoption("--pw-cart-suite"),
        "selected": len(session.items),
        "deselected": getattr(config, "_jujubit_daily_deselected", 0),
    }


@pytest.fixture(scope="session")
def playwright_runtime():
    """整个 pytest 会话只初始化一次 Playwright 运行时。"""
    with sync_playwright() as runtime:
        yield runtime


@pytest.fixture(scope="session")
def browser(playwright_runtime, request):
    """整个 pytest 会话复用一个浏览器进程；每条用例仍会创建独立上下文。"""
    launch_options = {"headless": not request.config.getoption("--headed")}
    # 录制视频时使用 Playwright Chromium；普通运行沿用本机 Chrome。
    if not request.config.getoption("--pw-record-video"):
        launch_options["channel"] = "chrome"
    instance = playwright_runtime.chromium.launch(**launch_options)
    yield instance
    instance.close()


class _CartContextPool:
    """按平台懒创建并复用购物车 Context，避免首页无意义地加载登录态。"""

    def __init__(self, browser, config, storage_state: Path):
        self.browser = browser
        self.config = config
        self.storage_state = storage_state
        self.contexts = {}
        self.video_dir = _artifact_dir(config) / "failure-videos" / "raw"

    def get(self, platform: str):
        """返回平台专属 Context；首次访问该平台时才导入登录态。"""
        if platform not in VIEWPORTS:
            raise ValueError(f"不支持的购物车测试平台：{platform}")
        context = self.contexts.get(platform)
        if context is not None:
            return context
        options = {
            "viewport": VIEWPORTS[platform],
            "storage_state": str(self.storage_state),
        }
        if platform == "h5":
            options.update(
                {"device_scale_factor": 3, "is_mobile": True, "has_touch": True}
            )
        if self.config.getoption("--pw-record-video"):
            self.video_dir.mkdir(parents=True, exist_ok=True)
            options["record_video_dir"] = str(self.video_dir)
        context = self.browser.new_context(**options)
        self.contexts[platform] = context
        return context

    def close(self) -> None:
        """关闭已经创建的 Context；未使用的平台不会产生额外浏览器状态。"""
        for context in self.contexts.values():
            try:
                context.close()
            except Exception:
                # 某个 Context 已异常关闭时，仍继续清理其它平台。
                pass


@pytest.fixture(scope="session")
def cart_contexts(browser, request):
    """为 PC/H5 各维护一个购物车登录上下文，跨 case 保留 Gallery 数据。"""
    storage_state = Path(request.config.getoption("--pw-storage-state")).expanduser()
    if not storage_state.is_absolute():
        storage_state = ROOT / storage_state
    pool = _CartContextPool(browser, request.config, storage_state)
    try:
        yield pool
    finally:
        # 关闭 Context 才会完成其中尚未关闭的 Playwright 录像文件。
        pool.close()


@pytest.fixture
def page(browser, cart_contexts, request, test_platform):
    """为每条 case 创建独立 Page；购物车 case 复用对应平台 Context。"""
    artifact_dir = _artifact_dir(request.config)
    is_cart_session = bool(request.node.get_closest_marker("cart_session"))
    is_membership_session = bool(
        request.node.get_closest_marker("membership_session")
    )
    needs_storage = is_cart_session or is_membership_session
    storage_state = Path(request.config.getoption("--pw-storage-state")).expanduser()
    if not storage_state.is_absolute():
        storage_state = ROOT / storage_state
    if needs_storage:
        # 购物车 / 会员登录态用例没有有效文件时不要先打开首页再逐条失败，
        # 否则会把无效配置放大成几十次站点请求，并更容易触发 429。
        storage_issue = _storage_state_issue(storage_state)
        if storage_issue:
            pytest.skip(storage_issue)
        rate_limit_reason = _active_rate_limit_reason(request.config)
        if rate_limit_reason:
            pytest.skip(rate_limit_reason)
    if is_cart_session:
        # 同一端的所有购物车 case 共享一个登录 Context，保留 Gallery 的
        # IndexedDB、localStorage 和 Cookie；每条 case 仍使用独立 Page。
        context = cart_contexts.get(test_platform)
    else:
        options = {"viewport": VIEWPORTS[test_platform]}
        if is_membership_session:
            # 会员登录态用例独立建 Context，不复用购物车池，避免互相污染 Gallery。
            options["storage_state"] = str(storage_state)
        if test_platform == "h5":
            options.update(
                {"device_scale_factor": 3, "is_mobile": True, "has_touch": True}
            )
        if request.config.getoption("--pw-record-video"):
            # 首页用例也必须把录像写入本次运行的临时目录；否则失败报告只有截图，
            # 即使命令行传入 --pw-record-video 也不会生成可点击的错误视频。
            raw_video_dir = artifact_dir / "failure-videos" / "raw"
            raw_video_dir.mkdir(parents=True, exist_ok=True)
            options["record_video_dir"] = str(raw_video_dir)
        context = browser.new_context(**options)
    current_page = context.new_page()
    if is_cart_session:
        _restore_cart_session_storage(current_page, request.config, test_platform)
    _apply_shop_mode(current_page, request.config)
    current_page.set_default_timeout(10_000)
    current_page.set_default_navigation_timeout(30_000)
    yield current_page
    failed = _test_has_failed(request.node)
    video = current_page.video if request.config.getoption("--pw-record-video") else None
    if failed:
        # 先保存页面 URL、滚动位置和测试提前标记的问题元素，再注入中文错误卡片。
        failure_context = _capture_failure_context(current_page, request.node)
        # 错误页有时禁止执行脚本；注入失败会被捕获，但不会影响录像收尾。
        _show_failure_overlay(current_page, request.node, failure_context)
        screenshots_dir = artifact_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _artifact_stem(request.config, request.node)
        screenshot_path = screenshots_dir / f"{safe_name}.png"
        # 使用视口截图，避免错误页整页截图阻塞测试收尾。
        try:
            current_page.screenshot(
                path=screenshot_path,
                full_page=False,
                animations="disabled",
                timeout=30_000,
            )
            if screenshot_path.is_file() and screenshot_path.stat().st_size > 0:
                _update_result(
                    request.config,
                    request.node.nodeid,
                    screenshot=f"screenshots/{safe_name}.png",
                    screenshot_error="",
                )
            # 让视频最后一帧保留中文错误卡片，便于非研发人员查看。
            current_page.wait_for_timeout(1_200)
        except Exception as error:
            _update_result(
                request.config,
                request.node.nodeid,
                screenshot_error=str(error).replace("\n", " ")[:300],
            )
    if is_cart_session:
        _capture_cart_session_storage(current_page, request.config, test_platform)
    # 共享购物车 Context 要继续服务后续 case；普通首页 Context 则在本条结束时关闭。
    current_page.close()
    if not is_cart_session:
        context.close()
    if video:
        destination_dir = artifact_dir / "failure-videos"
        destination_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _artifact_stem(request.config, request.node)
        destination = destination_dir / f"{safe_name}.webm" if failed else None
        try:
            if failed:
                # save_as 会等待当前 Page 的录像完成；不依赖 Context 已关闭，
                # 因而共享购物车 Context 也能在每条失败 case 后立即生成可点击视频。
                video.save_as(destination)
                # 只有保存后确认文件真实存在，报告才写入视频链接，避免产生 404。
                if destination.is_file() and destination.stat().st_size > 0:
                    _update_result(
                        request.config,
                        request.node.nodeid,
                        video=f"failure-videos/{safe_name}.webm",
                    )
            else:
                # 共享 Context 不会在每条 case 后自动删除成功录像，主动清理避免
                # 完整回归把 30 条无用原始录像留到 Artifact。
                video.delete()
        except Exception as error:
            if failed:
                _update_result(
                    request.config,
                    request.node.nodeid,
                    video_error=str(error).replace("\n", " ")[:300],
                )
    # 失败页面已经截图、Page 已关闭且录像已经另存，此时清车不会再改写证据；
    # fixture 返回前完成清理，下一条成功或失败用例仍从空购物车开始。
    if is_cart_session:
        _run_after_evidence_cleanups(request.node)


def _artifact_dir(config) -> Path:
    """返回本次执行的独立产物目录。"""
    configured = config.getoption("--pw-artifact-dir")
    return Path(configured) if configured else ROOT / "artifacts" / "latest"


def _active_rate_limit_reason(config) -> str:
    """返回仍在冷却窗口内的 429 熔断原因；已冷却则清空熔断并放行。

    没有冷却时，一次瞬时 429 会让整轮剩余购物车用例全部 skip（历史上出现过
    17/30、7/21）。冷却结束后允许下一条用例半开重试：站点已恢复就能真正执行，
    仍受限则会在请求路径上重新熔断并重新计时。
    """
    reason = (
        getattr(config, "_jujubit_cart_rate_limited", "")
        or getattr(config, "_jujubit_site_rate_limited", "")
    )
    if not reason:
        return ""
    try:
        cooldown = max(0.0, float(config.getoption("--pw-429-cooldown")))
    except (AttributeError, ValueError):
        cooldown = 0.0
    if cooldown <= 0:
        return reason
    opened_at = getattr(config, "_jujubit_cart_rate_limited_at", None)
    if opened_at is None:
        opened_at = getattr(config, "_jujubit_site_rate_limited_at", None)
    if opened_at is None:
        return reason
    if time.monotonic() - opened_at < cooldown:
        return reason
    config._jujubit_cart_rate_limited = ""
    config._jujubit_site_rate_limited = ""
    config._jujubit_cart_rate_limited_at = None
    config._jujubit_site_rate_limited_at = None
    return ""


def _storage_state_issue(path: Path) -> str:
    """在创建浏览器前检查登录态文件，避免无效登录反复访问站点。"""
    if not path.is_file():
        return (
            "缺少有效登录态：登录态文件不存在。请配置 GitHub Secret "
            "PLAYWRIGHT_STORAGE_STATE_JSON，或使用 --pw-storage-state 指向有效文件。"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return f"缺少有效登录态：登录态 JSON 无法读取（{error}）。"
    if not isinstance(payload, dict):
        return "缺少有效登录态：登录态 JSON 顶层必须是对象。"
    cookies = payload.get("cookies") or []
    origins = payload.get("origins") or []
    if not cookies and not origins:
        return "缺少有效登录态：登录态为空，请重新导出 storage-state.json。"
    # expiry=0 表示会话 Cookie；只有在所有持久化 Cookie 都过期时才判定失效。
    now = time.time()
    persistent = [cookie for cookie in cookies if float(cookie.get("expires") or 0) > 0]
    if persistent and all(float(cookie.get("expires") or 0) <= now for cookie in persistent):
        return "缺少有效登录态：storage-state.json 中的持久化 Cookie 已全部过期，请重新登录导出。"
    return ""


def _apply_shop_mode(page, config) -> None:
    """按 --pw-shop-mode 决定是否让前端走测试环境链路。

    默认 live 时什么都不做，保持线上行为——测试链路与线上不一致，
    日常回归不能用它验收。

    显式传 test 时用 add_init_script 而不是 evaluate + reload：
    init script 在每个文档的站点脚本之前执行，后续跳转（点 Get 跳
    Airwallex、切页签换 URL）也都带上，手工 reload 只对当前那一跳有效。
    """
    if config.getoption("--pw-shop-mode") != "test":
        return
    page.add_init_script(
        script="""(() => {
            try {
                window.localStorage.setItem('_shop_mode', 'test');
            } catch (error) {
                // about:blank 还不能访问 localStorage；真正导航后会再执行一次。
            }
        })();"""
    )


def _restore_cart_session_storage(page, config, platform: str) -> None:
    """在新 Page 的站点脚本执行前恢复同端上一条 case 的 sessionStorage。"""
    platforms = getattr(config, "_jujubit_cart_session_storage", {})
    state_by_origin = platforms.get(platform, {})
    if not state_by_origin:
        return
    serialized = json.dumps(state_by_origin, ensure_ascii=True)
    page.add_init_script(
        script=f"""(() => {{
            try {{
                const stateByOrigin = {serialized};
                const state = stateByOrigin[window.location.origin];
                if (!state) return;
                for (const [key, value] of Object.entries(state)) {{
                    window.sessionStorage.setItem(key, value);
                }}
            }} catch (error) {{
                // about:blank 暂时不能访问存储；真正导航后本脚本会再次执行。
            }}
        }})();"""
    )


def _capture_cart_session_storage(page, config, platform: str) -> None:
    """关闭 Page 前把当前来源的 sessionStorage 暂存到 pytest 进程内存。"""
    try:
        snapshot = page.evaluate(
            """() => ({
                origin: window.location.origin,
                entries: Object.fromEntries(Object.entries(window.sessionStorage)),
            })"""
        )
    except Exception:
        # 页面已崩溃或提前关闭时保留上一条成功取得的状态，不影响录像收尾。
        return
    origin = snapshot.get("origin", "") if isinstance(snapshot, dict) else ""
    entries = snapshot.get("entries", {}) if isinstance(snapshot, dict) else {}
    if not origin.startswith(("http://", "https://")) or not isinstance(entries, dict):
        return
    config._jujubit_cart_session_storage.setdefault(platform, {})[origin] = entries


def _run_after_evidence_cleanups(node) -> None:
    """在失败截图和录像保存完成后执行用例登记的幂等清理。

    清理列表会先从节点上移除，确保 fixture 收尾即使被重复调用也不会二次清车。
    清理本身不能覆盖原始业务失败或把已通过的用例改成 teardown error；下一条
    用例仍会通过 ``ensure_empty_cart`` 再次确认服务端状态。
    """
    cleanups = getattr(node, "_jujubit_after_evidence_cleanups", ())
    if hasattr(node, "_jujubit_after_evidence_cleanups"):
        delattr(node, "_jujubit_after_evidence_cleanups")
    for cleanup in cleanups:
        try:
            cleanup()
        except Exception:
            # CartPage 已使用 ignore_errors=True；这里再做最后防护，避免辅助清理
            # 掩盖真正的断言结果。下一条 case 的前置检查仍会负责兜底清车。
            pass


def _artifact_stem(config, node) -> str:
    """生成同时包含运行时间和用例名的安全文件名。"""
    run_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", _artifact_dir(config).name) or "run"
    test_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", node.name)
    return f"{run_name}-{test_name}"


def _report_path(config) -> Path:
    """根据命令行传入的报告文件名定位 HTML，避免固定写死 report.html。"""
    configured = config.getoption("--pw-report-name") or "report.html"
    return _artifact_dir(config) / Path(configured).name


def _test_has_failed(node) -> bool:
    # 页面 fixture 收尾时只能读取 setup/call 阶段，teardown 报告会在其后生成。
    return any(
        bool(getattr(node, f"rep_{phase}", None) and getattr(node, f"rep_{phase}").failed)
        for phase in ("setup", "call")
    )


def _update_result(config, nodeid: str, **values) -> None:
    """在 fixture 收尾阶段补充截图、录像和页面定位信息。"""
    result = config._jujubit_results.get(nodeid)
    if result:
        result.update(values)


def _capture_failure_context(page, node) -> dict:
    """记录失败发生时的页面路径、截图视口和显式标记的问题元素。"""
    context = {
        "page_url": "",
        "page_path": "",
        "page_title": "",
        "scroll_x": 0,
        "scroll_y": 0,
        "viewport_width": 0,
        "viewport_height": 0,
        "evidence": {},
    }
    if page.is_closed():
        return context
    try:
        context.update(
            page.evaluate(
                """() => ({
                    page_url: location.href,
                    page_path: `${location.pathname}${location.search}${location.hash}`,
                    page_title: document.title,
                    scroll_x: Math.round(window.scrollX),
                    scroll_y: Math.round(window.scrollY),
                    viewport_width: window.innerWidth,
                    viewport_height: window.innerHeight,
                    evidence: window.__jujubitTestEvidence || {},
                })"""
            )
        )
    except Exception:
        try:
            context["page_url"] = page.url
        except Exception:
            pass
    _update_result(node.config, node.nodeid, **context)
    return context


def _show_failure_overlay(page, node, context: dict) -> None:
    """把失败摘要写到录像最后一帧，方便非研发人员直接定位问题。"""
    report = getattr(node, "rep_call", None) or getattr(node, "rep_setup", None)
    if not report or page.is_closed():
        return
    function_name = node.originalname or node.name.split("[")[0]
    platform = node.callspec.params.get("test_platform", "通用").upper() if hasattr(node, "callspec") else "通用"
    detail = str(report.longrepr).replace("\n", " ")[:900]
    evidence = context.get("evidence") or {}
    page_path = context.get("page_path") or context.get("page_url") or "未取得"
    element_path = evidence.get("selector") or "未指定具体元素"
    try:
        page.evaluate(
            """({ title, platform, detail, pagePath, elementPath }) => {
                const existing = document.getElementById('jujubit-test-failure-overlay');
                if (existing) existing.remove();
                const card = document.createElement('section');
                card.id = 'jujubit-test-failure-overlay';
                card.setAttribute('role', 'alert');
                const heading = document.createElement('strong');
                heading.textContent = `自动化发现问题（${platform}）`;
                const caseTitle = document.createElement('div');
                caseTitle.textContent = title;
                const errorDetail = document.createElement('small');
                errorDetail.textContent = `页面路径：${pagePath}\n元素路径：${elementPath}\n${detail}`;
                card.append(heading, caseTitle, errorDetail);
                Object.assign(card.style, {
                    position: 'fixed', zIndex: '2147483647', left: '16px', right: '16px',
                    padding: '16px', borderRadius: '10px', background: '#8b1e1e', color: '#fff',
                    fontFamily: 'Arial, sans-serif', fontSize: '16px', lineHeight: '1.45', boxShadow: '0 4px 20px #0008'
                });
                // 页底问题把错误卡片放在顶部，避免遮住刚滚动到画面中的真实控件。
                const nearPageBottom = window.scrollY + window.innerHeight >=
                    document.documentElement.scrollHeight - 120;
                card.style.top = nearPageBottom ? '16px' : 'auto';
                card.style.bottom = nearPageBottom ? 'auto' : '16px';
                errorDetail.style.display = 'block';
                errorDetail.style.marginTop = '8px';
                errorDetail.style.fontSize = '12px';
                errorDetail.style.whiteSpace = 'pre-wrap';
                document.body.appendChild(card);
            }""",
            {
                "title": CASE_TITLES.get(function_name, function_name),
                "platform": platform,
                "detail": detail,
                "pagePath": page_path,
                "elementPath": element_path,
            },
        )
    except Exception:
        # 即使错误页禁止注入脚本，原始页面录像仍会保留，便于复盘。
        pass


@pytest.fixture
def home(page, request):
    """打开首页并返回页面对象，供测试用例调用可复用的页面操作。"""
    instance = HomePage(page, request.config.getoption("--base-url"), request.config)
    try:
        instance.open()
    except SiteRateLimitError as error:
        # 429 不代表页面功能不符合需求；让 pytest、HTML 和飞书统一标为未完成。
        pytest.skip(str(error))
    return instance


def pytest_configure(config):
    """初始化本次运行的计时、报告结果和全局请求限速器。"""
    config._jujubit_started_at = time.time()
    config._jujubit_results = {}
    # 所有访问 jujubit.ai 的动作共用一个节流器。取两种配置的较大值，确保链接扫描
    # 不会以比首页导航更高的频率打到同一个 Shopify/WAF 出口。
    interval = max(
        config.getoption("--pw-request-interval"),
        config.getoption("--pw-link-request-interval"),
        config.getoption("--pw-cart-request-interval"),
    )
    # 首页、Creator 导航和购物车 API 命中同一站点/WAF，必须共享一个时钟；
    # 分开计时仍可能出现 clear.js 后立刻打开首页的突发请求。
    shared_pacer = SiteRequestPacer(interval)
    config._jujubit_site_pacer = shared_pacer
    config._jujubit_cart_pacer = shared_pacer
    # 429 熔断：首次持续受限后，不再让剩余购物车用例继续撞同一出口 IP。
    # 熔断带冷却（--pw-429-cooldown），冷却结束后下一条用例会半开重试，
    # 避免一次瞬时频控把整轮剩余用例全部标为“未完成”。
    config._jujubit_cart_rate_limited = ""
    config._jujubit_site_rate_limited = ""
    config._jujubit_cart_rate_limited_at = None
    config._jujubit_site_rate_limited_at = None
    config._jujubit_link_probe_cache = {}
    # 只在当前 pytest 进程内按平台/来源传递，不写入报告或 Artifact。
    config._jujubit_cart_session_storage = {}


def pytest_html_report_title(report):
    """把 pytest-html 的默认英文标题和结果名称改为中文。"""
    report.title = "JuJuBit 自动化测试报告"
    labels = {
        "failed": "失败",
        "passed": "通过",
        "skipped": "跳过",
        "xfailed": "预期失败",
        "xpassed": "意外通过",
        "error": "错误",
        "rerun": "重新运行",
    }
    for outcome, label in labels.items():
        report.outcomes[outcome]["label"] = label


def pytest_html_results_summary(prefix, summary, postfix, session):
    """在报告顶部输出独立的通过、失败、跳过用例明细表。

    渲染逻辑在 python_playwright/report_summary.py。这里只负责从 session.config
    取数据——hook 必须留在 conftest 才能被 pytest 发现，但纯函数部分抽出去后
    可以直接测，不用伪造 session。
    """
    results = list(getattr(session.config, "_jujubit_results", {}).values())
    if not results:
        return
    collection = getattr(session.config, "_jujubit_collection_counts", {})
    prefix.append(
        build_summary_html(
            results,
            suite_name=getattr(session.config, "_jujubit_suite_name", "默认回归"),
            selected_count=collection.get("selected", len(results)),
            deselected_count=collection.get("deselected", 0),
        )
    )


def _case_title(function_name, variant: str = ""):
    """将 Python 函数名映射成报告中面向业务的中文标题。

    契约层按契约名参数化（同一个函数产出 8 条记录），必须把该参数附在标题上，
    否则报告里 8 行完全同名、无法区分是哪条契约失败。
    """
    title = CASE_TITLES.get(function_name, function_name)
    return f"{title}：{variant}" if variant else title


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_sessionfinish(session, exitstatus):
    yield
    # pytest-html 写完文件后再统一替换标题和固定英文提示。
    report_path = _report_path(session.config)
    if not report_path.exists():
        return
    content = report_path.read_text(encoding="utf-8")
    content = re.sub(
        r'(<title id="head-title">)[^<]*(</title>)',
        r'\1JuJuBit 自动化测试报告\2',
        content,
    )
    content = re.sub(
        r'(<h1 id="title">)[^<]*(</h1>)',
        r'\1JuJuBit 自动化测试报告\2',
        content,
    )
    replacements = {
        "<h2>Summary</h2>": "<h2>执行汇总</h2>",
        "<h2>Environment</h2>": "<h2>运行环境</h2>",
        "Report generated on ": "报告生成于 ",
        "(Un)check the boxes to filter the results.": "勾选或取消勾选以筛选结果。",
        "Show all details": "展开全部详情",
        "Hide all details": "收起全部详情",
        "No results found. Check the filters.": "没有符合当前筛选条件的结果。",
        ">Result</th>": ">结果</th>",
        ">Test</th>": ">测试用例</th>",
        ">Duration</th>": ">耗时</th>",
        ">Links</th>": ">附件</th>",
        " tests took ": " 条用例，耗时 ",
        " test took ": " 条用例，耗时 ",
    }
    for source, target in replacements.items():
        content = content.replace(source, target)
    report_path.write_text(content, encoding="utf-8")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """收集每条 case 的最终状态，为报告和失败录像链接提供数据。

    顺带把"环境本身没放开功能"从失败改判为未完成：付费墙 Coming Soon 时
    卡片被全屏遮罩挡死，交互必然失败，但那不是站点坏了。统一在 hook 里转，
    16 处 wait_for_paywall 调用点不必各写一遍 try/except，新用例也自动生效。
    """
    outcome = yield
    report = outcome.get_result()
    if (
        report.when == "call"
        and report.failed
        and call.excinfo is not None
        and call.excinfo.errisinstance(MembershipNotLaunchedError)
    ):
        report.outcome = "skipped"
        report.longrepr = (__file__, None, f"Skipped: {call.excinfo.value}")
    setattr(item, f"rep_{report.when}", report)
    if report.when == "call" or report.failed or (report.when == "setup" and report.skipped):
        function_name = item.originalname or item.name.split("[")[0]
        params = getattr(item, "callspec", None)
        params = params.params if params is not None else {}
        # 契约层不分 PC/H5（同一份服务端 HTML 两端相同），如实标为 server
        # 而不是 unknown，避免读报告时误以为平台信息丢失。
        default_platform = "server" if "contract_name" in params else "unknown"
        platform = params.get("test_platform", default_platform)
        # 契约层不参与 PC/H5 参数化，改用契约名区分同一函数的多条记录。
        variant = str(params.get("contract_name", ""))
        previous = item.config._jujubit_results.get(item.nodeid, {})
        if report.when == "call":
            result_outcome = report.outcome
        elif getattr(report, "wasxfail", None):
            result_outcome = "xfailed" if report.outcome == "skipped" else "xpassed"
        elif report.skipped:
            # setup 阶段的 429 会走这里；必须保留为 skipped，不能误写成 error。
            result_outcome = "skipped"
        else:
            result_outcome = "error"
        item.config._jujubit_results[item.nodeid] = {
            "platform": platform,
            "title": _case_title(function_name, variant),
            "outcome": result_outcome,
            "detail": _report_detail(report) if result_outcome != "passed" else previous.get("detail", ""),
            "video": previous.get("video", ""),
            "video_error": previous.get("video_error", ""),
            "screenshot": previous.get("screenshot", ""),
            "screenshot_error": previous.get("screenshot_error", ""),
            "page_url": previous.get("page_url", ""),
            "page_path": previous.get("page_path", ""),
            "page_title": previous.get("page_title", ""),
            "scroll_x": previous.get("scroll_x", 0),
            "scroll_y": previous.get("scroll_y", 0),
            "viewport_width": previous.get("viewport_width", 0),
            "viewport_height": previous.get("viewport_height", 0),
            "evidence": previous.get("evidence", {}),
        }


def _report_detail(report) -> str:
    """把 pytest 的长错误压缩成报告中可读的一行。

    频控判定复用 home_page.RATE_LIMIT_DETAIL_PATTERN。原先用
    ``(?:http\\s*)?429`` 匹配，http 前缀可选，于是裸的 429 三个数字就命中：
    "Timeout 30000ms exceeded ... at cart_page.py:1429"、"元素宽 429px"、
    "assert 429 == 430"、"home_page.py:429: in click_unobstructed" 全部误判。
    误判后 detail 被整段替换成频控说明，真实错误信息完全丢失。
    """
    detail = str(report.longrepr).replace("\n", " ").strip()
    if RATE_LIMIT_DETAIL_PATTERN.search(detail):
        return (
            "站点访问频控（HTTP 429）：本条用例未能执行，不代表页面功能失败。"
            "脚本已自动限速并重试；仍持续出现时请稍后重跑，或使用 "
            "`run_all.py --manual-verification` 在可见浏览器中手动完成网站验证。"
        )
    return detail[:1_200] if detail else "未提供错误详情"


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """在终端打印本次运行的中文汇总和报告路径。"""
    results = list(config._jujubit_results.values())
    # 共享 Context 的离线生命周期单测不带平台参数，也不会经过 page fixture；
    # 它们由 pytest 正常计数，但不应被伪装成一次真实线上 UI 回归结果。
    if not results:
        return
    passed = sum(item["outcome"] == "passed" for item in results)
    failed = sum(item["outcome"] in {"failed", "error", "xpassed"} for item in results)
    skipped = sum(item["outcome"] in {"skipped", "xfailed"} for item in results)
    seconds = round(time.time() - config._jujubit_started_at)
    duration = f"{seconds // 60}分{seconds % 60}秒" if seconds >= 60 else f"{seconds}秒"
    started = datetime.fromtimestamp(config._jujubit_started_at).strftime("%Y/%m/%d %H:%M:%S")
    # 只看 failed 会把“17/30 未完成”也写成执行通过，掩盖真实覆盖率。
    # 未完成的用例既不是通过也不是失败，必须单独显性化。
    if failed:
        verdict = "执行失败"
    elif skipped:
        verdict = f"执行完成但 {skipped}/{len(results)} 条未完成"
    else:
        verdict = "执行通过"
    terminalreporter.write_sep("=", f"[JuJuBit UI Python] {verdict}")
    suite_name = getattr(config, "_jujubit_suite_name", "默认回归")
    collection = getattr(config, "_jujubit_collection_counts", {})
    selected_count = collection.get("selected", len(results))
    deselected_count = collection.get("deselected", 0)
    terminalreporter.write_line(f"执行套件：{suite_name}")
    terminalreporter.write_line(
        f"本次收集：{selected_count} 条"
        + (f"（分层排除 {deselected_count} 条 H5 深度用例）" if deselected_count else "")
    )
    terminalreporter.write_line(f"机器：{socket.gethostname()}")
    terminalreporter.write_line(f"开始：{started}")
    terminalreporter.write_line(f"耗时：{duration}")
    terminalreporter.write_line(f"结果：共 {len(results)}，通过 {passed}，失败 {failed}，跳过 {skipped}")
    # 真实覆盖率 = 实际得出业务结论的用例 / 计划用例。跳过的用例没有验证任何
    # 业务行为，把它们算进“通过率”会让报告看起来比实际可信。
    if skipped:
        executed = passed + failed
        coverage = executed / len(results) * 100 if results else 0.0
        terminalreporter.write_line(
            f"有效覆盖：{coverage:.0f}%（{executed}/{len(results)} 条得出业务结论；"
            f"{skipped} 条未完成，未验证任何业务行为）"
        )
    terminalreporter.write_line("全部用例：")
    for item in results:
        terminalreporter.write_line(f"- [{RESULT_LABELS.get(item['outcome'], '⚠ 未知')}] [{item['platform']}] {item['title']}")
    terminalreporter.write_line(f"本机报告：{_report_path(config)}")
