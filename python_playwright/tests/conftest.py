"""pytest + Playwright 共享夹具和中文报告生成逻辑。

pytest 会在运行每条 ``test_...`` 用例前自动调用本文件中的夹具：创建浏览器、
设置 PC/H5 视口、打开首页；运行结束后再把结果、截图和失败录像写进 HTML 报告。
"""

from datetime import datetime
from pathlib import Path
import re
import shutil
import socket
import time
from html import escape

import pytest
from playwright.sync_api import sync_playwright

from python_playwright.pages.home_page import HomePage


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
    "test_configured_internal_links_are_available": "REQ-04: 首页实际配置的站内链接均可访问且不是白屏",
    "test_configured_navigation_and_hero_links_can_open": "REQ-04B: 首页配置的导航与 Hero 链接可真实打开",
    "test_footer_locale_switcher_is_available": "REQ-05: Footer 地区与币种切换器可见且可展开",
    "test_external_social_links_are_safe": "REQ-06: 外部社交链接具备安全 rel 属性",
    "test_homepage_links_are_real_anchors": "REQ-07: 首页导航与 CTA 使用真实链接",
    "test_social_videos_have_inline_playback_attributes": "REQ-08: 社交视频具备移动端内联静音循环属性",
    "test_faq_semantics_and_single_expansion": "REQ-09: FAQ 语义结构正确且只展开一项",
    "test_hero_heading_hierarchy": "REQ-10: Hero 标题使用 H2 层级",
}

RESULT_LABELS = {
    "passed": "✅ 通过",
    "failed": "❌ 失败",
    "skipped": "⏭ 跳过",
    "error": "⚠ 错误",
    "xfailed": "预期失败",
    "xpassed": "意外通过",
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


@pytest.fixture
def page(browser, request, test_platform):
    """为每条 case 创建干净浏览器上下文，并在失败时保存可复盘的证据。"""
    artifact_dir = _artifact_dir(request.config)
    options = {"viewport": VIEWPORTS[test_platform]}
    if test_platform == "h5":
        options.update({"device_scale_factor": 3, "is_mobile": True, "has_touch": True})
    if request.config.getoption("--pw-record-video"):
        # Playwright 先写入随机名原始录像，失败后再复制为带时间戳的可读文件名。
        video_dir = artifact_dir / "failure-videos" / "raw"
        video_dir.mkdir(parents=True, exist_ok=True)
        options["record_video_dir"] = str(video_dir)
    context = browser.new_context(**options)
    current_page = context.new_page()
    current_page.set_default_timeout(10_000)
    current_page.set_default_navigation_timeout(30_000)
    yield current_page
    failed = _test_has_failed(request.node)
    video = current_page.video if request.config.getoption("--pw-record-video") else None
    if failed:
        # 错误页有时禁止执行脚本；注入失败会被捕获，但不会影响录像收尾。
        _show_failure_overlay(current_page, request.node)
        screenshots_dir = artifact_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _artifact_stem(request.config, request.node)
        # 使用视口截图，避免错误页整页截图阻塞测试收尾。
        try:
            current_page.screenshot(path=screenshots_dir / f"{safe_name}.png", full_page=False)
            # 让视频最后一帧保留中文错误卡片，便于非研发人员查看。
            current_page.wait_for_timeout(1_200)
        except Exception:
            pass
    context.close()
    if failed and video:
        destination_dir = artifact_dir / "failure-videos"
        destination_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _artifact_stem(request.config, request.node)
        destination = destination_dir / f"{safe_name}.webm"
        try:
            source = Path(video.path())
            if source.is_file():
                shutil.copy2(source, destination)
                # 只有复制后确认文件真实存在，报告才写入视频链接，避免产生 404。
                if destination.is_file() and destination.stat().st_size > 0:
                    _set_video_path(request.config, request.node.nodeid, f"failure-videos/{safe_name}.webm")
        except Exception:
            pass


def _artifact_dir(config) -> Path:
    """返回本次执行的独立产物目录。"""
    configured = config.getoption("--pw-artifact-dir")
    return Path(configured) if configured else ROOT / "artifacts" / "latest"


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


def _set_video_path(config, nodeid: str, video_path: str) -> None:
    result = config._jujubit_results.get(nodeid)
    if result:
        result["video"] = video_path


def _show_failure_overlay(page, node) -> None:
    """把失败摘要写到录像最后一帧，方便非研发人员直接定位问题。"""
    report = getattr(node, "rep_call", None) or getattr(node, "rep_setup", None)
    if not report or page.is_closed():
        return
    function_name = node.originalname or node.name.split("[")[0]
    platform = node.callspec.params.get("test_platform", "通用").upper() if hasattr(node, "callspec") else "通用"
    detail = str(report.longrepr).replace("\n", " ")[:900]
    try:
        page.evaluate(
            """({ title, platform, detail }) => {
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
                errorDetail.textContent = detail;
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
                document.body.appendChild(card);
            }""",
            {"title": CASE_TITLES.get(function_name, function_name), "platform": platform, "detail": detail},
        )
    except Exception:
        # 即使错误页禁止注入脚本，原始页面录像仍会保留，便于复盘。
        pass


@pytest.fixture
def home(page, request):
    """打开首页并返回页面对象，供测试用例调用可复用的页面操作。"""
    instance = HomePage(page, request.config.getoption("--base-url"), request.config)
    instance.open()
    return instance


def pytest_configure(config):
    """初始化本次运行的计时、报告结果和全局请求限速器。"""
    config._jujubit_started_at = time.time()
    config._jujubit_results = {}
    config._jujubit_site_pacer = SiteRequestPacer(config.getoption("--pw-request-interval"))
    config._jujubit_link_pacer = SiteRequestPacer(config.getoption("--pw-link-request-interval"))


def pytest_html_report_title(report):
    """把 pytest-html 的默认英文标题和结果名称改为中文。"""
    report.title = "JuJuBit 首页自动化测试报告"
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
    """在报告顶部输出独立的通过、失败、跳过用例明细表。"""
    results = list(getattr(session.config, "_jujubit_results", {}).values())
    if not results:
        return
    # 报告首页直接输出中文明细，避免用户还要在 pytest-html 原始表格中筛选。
    passed = [item for item in results if item["outcome"] == "passed"]
    failed = [
        item
        for item in results
        if item["outcome"] in {"failed", "error", "xpassed"}
    ]
    skipped = [
        item
        for item in results
        if item["outcome"] in {"skipped", "xfailed"}
    ]

    def rows(items, include_video=False):
        content = []
        for item in items:
            status = RESULT_LABELS.get(item["outcome"], "⚠ 未知")
            detail = escape(item.get("detail") or "未提供错误详情")
            video = "未生成"
            if include_video and item.get("video"):
                video = (
                    f'<a target="_blank" rel="noopener" '
                    f'href="{escape(item["video"])}">播放错误视频</a>'
                )
            detail_cell = f"<td>{detail}</td>" if include_video else ""
            video_cell = f"<td>{video}</td>" if include_video else ""
            content.append(
                f'<tr><td>{status}</td><td>[{escape(str(item["platform"]).upper())}] '
                f'{escape(item["title"])}</td>{detail_cell}{video_cell}</tr>'
            )
        colspan = 4 if include_video else 2
        return "".join(content) or f'<tr><td colspan="{colspan}">无</td></tr>'

    prefix.append(
        '<style>#results-table,.controls{display:none}.jujubit-summary{margin:12px 0;border-collapse:collapse;width:100%}'
        '.jujubit-summary td,.jujubit-summary th{border:1px solid #d9dee8;padding:7px;text-align:left}'
        '.jujubit-summary th{background:#f3f5f8}.jujubit-summary td{vertical-align:top}'
        '</style>'
        f'<h3>通过用例（{len(passed)}）</h3>'
        '<table class="jujubit-summary"><thead><tr><th>结果</th><th>用例</th></tr></thead><tbody>'
        f'{rows(passed)}</tbody></table>'
        f'<h3>失败用例（{len(failed)}）</h3>'
        '<table class="jujubit-summary"><thead><tr><th>结果</th><th>用例</th><th>错误说明</th><th>视频</th></tr></thead><tbody>'
        f'{rows(failed, include_video=True)}</tbody></table>'
        + (
            f'<h3>跳过用例（{len(skipped)}）</h3>'
            '<table class="jujubit-summary"><thead><tr><th>结果</th><th>用例</th></tr></thead><tbody>'
            f'{rows(skipped)}</tbody></table>'
            if skipped
            else ""
        )
    )


def _case_title(function_name):
    """将 Python 函数名映射成报告中面向业务的中文标题。"""
    return CASE_TITLES.get(function_name, function_name)


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
        r'\1JuJuBit 首页自动化测试报告\2',
        content,
    )
    content = re.sub(
        r'(<h1 id="title">)[^<]*(</h1>)',
        r'\1JuJuBit 首页自动化测试报告\2',
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
    """收集每条 case 的最终状态，为报告和失败录像链接提供数据。"""
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)
    if report.when == "call" or report.failed or (report.when == "setup" and report.skipped):
        function_name = item.originalname or item.name.split("[")[0]
        platform = item.callspec.params.get("test_platform", "unknown") if hasattr(item, "callspec") else "unknown"
        previous = item.config._jujubit_results.get(item.nodeid, {})
        if report.when == "call":
            result_outcome = report.outcome
        elif getattr(report, "wasxfail", None):
            result_outcome = "xfailed" if report.outcome == "skipped" else "xpassed"
        else:
            result_outcome = "error"
        item.config._jujubit_results[item.nodeid] = {
            "platform": platform,
            "title": _case_title(function_name),
            "outcome": result_outcome,
            "detail": _report_detail(report) if result_outcome != "passed" else previous.get("detail", ""),
            "video": previous.get("video", ""),
        }


def _report_detail(report) -> str:
    """把 pytest 的长错误压缩成报告中可读的一行。"""
    detail = str(report.longrepr).replace("\n", " ").strip()
    if "HTTP 429" in detail:
        return (
            "站点访问频控（HTTP 429）：本条用例未能执行，不代表页面功能失败。"
            "脚本已自动限速并重试；仍持续出现时请稍后重跑，或使用 "
            "`run_all.py --manual-verification` 在可见浏览器中手动完成网站验证。"
        )
    return detail[:1_200] if detail else "未提供错误详情"


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """在终端打印本次运行的中文汇总和报告路径。"""
    results = list(config._jujubit_results.values())
    passed = sum(item["outcome"] == "passed" for item in results)
    failed = sum(item["outcome"] in {"failed", "error", "xpassed"} for item in results)
    skipped = sum(item["outcome"] in {"skipped", "xfailed"} for item in results)
    seconds = round(time.time() - config._jujubit_started_at)
    duration = f"{seconds // 60}分{seconds % 60}秒" if seconds >= 60 else f"{seconds}秒"
    started = datetime.fromtimestamp(config._jujubit_started_at).strftime("%Y/%m/%d %H:%M:%S")
    terminalreporter.write_sep("=", f"[JuJuBit UI Python] {'执行通过' if not failed else '执行失败'}")
    terminalreporter.write_line(f"模式：全部 {len(results)} 条（真实生成）")
    terminalreporter.write_line(f"机器：{socket.gethostname()}")
    terminalreporter.write_line(f"开始：{started}")
    terminalreporter.write_line(f"耗时：{duration}")
    terminalreporter.write_line(f"结果：共 {len(results)}，通过 {passed}，失败 {failed}，跳过 {skipped}")
    terminalreporter.write_line("全部用例：")
    for item in results:
        terminalreporter.write_line(f"- [{RESULT_LABELS.get(item['outcome'], '⚠ 未知')}] [{item['platform']}] {item['title']}")
    terminalreporter.write_line(f"本机报告：{_report_path(config)}")
