"""HTML 报告首屏摘要的生成逻辑。

从 conftest.py 抽出来的原因：这部分有 180 行、是 conftest 里最大的一块，但它
不含任何 pytest hook 契约——输入是结果列表，输出是 HTML 字符串，纯函数。留在
conftest 里只能靠伪造 session 对象来测，抽出来后可以直接调用。

判定口径（失败与未完成分开计量）集中在 ``compute_verdict``，它不产出任何 HTML，
因此报告口径的回归测试不需要解析 HTML 字符串。
"""

from __future__ import annotations

from html import escape
from typing import Any, Iterable, Optional

RESULT_LABELS = {
    "passed": "✅ 通过",
    "failed": "❌ 失败",
    "skipped": "⏭ 跳过",
    "error": "⚠ 错误",
    "xfailed": "预期失败",
    "xpassed": "意外通过",
}

# 判定为"业务失败"与"未完成"的结果类别。xpassed（意外通过）算失败：它说明
# 用例的预期标记已经过时，需要人处理。
FAILED_OUTCOMES = frozenset({"failed", "error", "xpassed"})
UNFINISHED_OUTCOMES = frozenset({"skipped", "xfailed"})

BANNER_FAILED = "#ffecec"
BANNER_UNFINISHED = "#fff6e5"
BANNER_PASSED = "#eef5ff"

_STYLE = (
    "<style>#results-table,.controls{display:none}"
    ".jujubit-summary{margin:12px 0;border-collapse:collapse;width:100%}"
    ".jujubit-summary td,.jujubit-summary th"
    "{border:1px solid #d9dee8;padding:7px;text-align:left}"
    ".jujubit-summary th{background:#f3f5f8}"
    ".jujubit-summary td{vertical-align:top;word-break:break-word}"
    ".jujubit-summary code{white-space:normal;word-break:break-all}"
    "</style>"
)


class Verdict:
    """一轮运行的结论与覆盖率。

    失败与未完成是两个口径：未完成的用例没有验证任何业务行为，既不能算通过也
    不能算失败。只看 failed 会把"13 通过 + 17 未完成"写成执行通过（通过率
    100%），而实际有效覆盖只有 43%。
    """

    def __init__(self, results: Iterable[dict[str, Any]]):
        items = list(results)
        self.total = len(items)
        self.passed = [item for item in items if item.get("outcome") == "passed"]
        self.failed = [
            item for item in items if item.get("outcome") in FAILED_OUTCOMES
        ]
        self.unfinished = [
            item for item in items if item.get("outcome") in UNFINISHED_OUTCOMES
        ]
        # pytest 未来新增结果类别、或上游改名时，这些用例既不在三类里又计入
        # total，会从报告中彻底消失且结论仍显示"执行通过"。归入失败：宁可报错
        # 让人来看，也不能静默丢弃一条用例的结果。
        classified = {"passed", *FAILED_OUTCOMES, *UNFINISHED_OUTCOMES}
        self.unclassified = [
            item for item in items if item.get("outcome") not in classified
        ]
        if self.unclassified:
            self.failed = self.failed + self.unclassified
        self.rate_limited = sum(
            "HTTP 429" in (item.get("detail") or "") for item in self.unfinished
        )

    @property
    def executed(self) -> int:
        """真正得出业务结论的用例数。"""
        return len(self.passed) + len(self.failed)

    @property
    def coverage(self) -> float:
        """有效覆盖百分比；判断本轮结果可不可信看这个，而不是通过率。"""
        return self.executed / self.total * 100 if self.total else 0.0

    @property
    def headline(self) -> str:
        if self.failed:
            return f"执行失败：{len(self.failed)}/{self.total} 条业务失败"
        if self.unfinished:
            return f"执行完成但 {len(self.unfinished)}/{self.total} 条未完成"
        return "执行通过"

    @property
    def banner_color(self) -> str:
        if self.failed:
            return BANNER_FAILED
        if self.unfinished:
            return BANNER_UNFINISHED
        return BANNER_PASSED

    @property
    def coverage_text(self) -> str:
        text = f"{self.coverage:.0f}%（{self.executed}/{self.total} 条得出业务结论"
        if self.unfinished:
            return (
                text
                + f"；{len(self.unfinished)} 条未完成，"
                + f"其中因 HTTP 429 未完成 {self.rate_limited} 条，未验证任何业务行为）"
            )
        return text + "）"


def compute_verdict(results: Iterable[dict[str, Any]]) -> Verdict:
    """按失败/未完成两个口径汇总一轮运行结果。"""
    return Verdict(results)


def _platform_label(item: dict[str, Any]) -> str:
    return escape(str(item.get("platform", "unknown")).upper())


def _status_label(item: dict[str, Any]) -> str:
    return RESULT_LABELS.get(item.get("outcome", ""), "⚠ 未知")


def _simple_rows(items: list[dict[str, Any]]) -> str:
    content = [
        f"<tr><td>{_status_label(item)}</td>"
        f'<td>[{_platform_label(item)}] {escape(item.get("title", ""))}</td></tr>'
        for item in items
    ]
    return "".join(content) or '<tr><td colspan="2">无</td></tr>'


def _skipped_rows(items: list[dict[str, Any]]) -> str:
    """展示未完成原因，避免把 429 和普通跳过混为一谈。"""
    content = [
        f"<tr><td>{_status_label(item)}</td>"
        f'<td>[{_platform_label(item)}] {escape(item.get("title", ""))}</td>'
        f'<td>{escape(item.get("detail") or "未提供跳过原因")}</td></tr>'
        for item in items
    ]
    return "".join(content) or '<tr><td colspan="3">无</td></tr>'


def _failure_location(item: dict[str, Any]) -> str:
    """生成页面地址、DOM 路径和截图视口说明。"""
    page_url = item.get("page_url") or ""
    page_path = item.get("page_path") or page_url or "未取得"
    page_title = item.get("page_title") or "未取得"
    if page_url:
        page_link = (
            f'<a target="_blank" rel="noopener" href="{escape(page_url)}">'
            f"{escape(page_path)}</a>"
        )
    else:
        page_link = escape(page_path)
    parts = [f"页面：{page_link}", f"标题：{escape(page_title)}"]
    evidence = item.get("evidence") or {}
    if evidence.get("selector"):
        parts.append(f"定位器：<code>{escape(str(evidence['selector']))}</code>")
    if evidence.get("description"):
        parts.append(f"元素：{escape(str(evidence['description']))}")
    if evidence.get("viewport"):
        parts.append(f"视口：{escape(str(evidence['viewport']))}")
    return "<br>".join(parts)


def _attachment_cell(item: dict[str, Any]) -> str:
    attachments: list[str] = []
    if item.get("screenshot"):
        attachments.append(
            f'<a target="_blank" rel="noopener" href="{escape(item["screenshot"])}">'
            "查看失败截图</a>"
        )
    elif item.get("screenshot_error"):
        attachments.append(f"截图未生成：{escape(item['screenshot_error'])}")
    else:
        attachments.append("截图未生成")
    if item.get("video"):
        attachments.append(
            f'<a target="_blank" rel="noopener" href="{escape(item["video"])}">'
            "播放错误视频</a>"
        )
    elif item.get("video_error"):
        attachments.append(f"视频未生成：{escape(item['video_error'])}")
    else:
        attachments.append("视频未生成")
    return "<br>".join(attachments)


def _failure_rows(items: list[dict[str, Any]]) -> str:
    content = []
    for item in items:
        case_cell = (
            f"<strong>{_status_label(item)}</strong><br>"
            f'[{_platform_label(item)}] {escape(item.get("title", ""))}'
        )
        detail = escape(item.get("detail") or "未提供错误详情")
        content.append(
            f"<tr><td>{case_cell}</td><td>{_failure_location(item)}</td>"
            f"<td>{detail}</td><td>{_attachment_cell(item)}</td></tr>"
        )
    return "".join(content) or '<tr><td colspan="4">无</td></tr>'


def build_summary_html(
    results: Iterable[dict[str, Any]],
    *,
    suite_name: str = "默认回归",
    selected_count: Optional[int] = None,
    deselected_count: int = 0,
) -> str:
    """生成报告首屏的结论横幅与三张明细表；无结果时返回空串。"""
    items = list(results)
    if not items:
        return ""
    verdict = compute_verdict(items)
    if selected_count is None:
        selected_count = verdict.total

    banner = (
        f'<div class="jujubit-summary" style="padding:10px;'
        f'background:{verdict.banner_color};border:1px solid #b8d4ff">'
        f"<strong>{escape(verdict.headline)}</strong><br>"
        f"<strong>执行套件：</strong>{escape(str(suite_name))}；"
        f"<strong>本次收集：</strong>{selected_count} 条"
        + (
            f"（分层排除 {deselected_count} 条 H5 深度用例）"
            if deselected_count
            else ""
        )
        + f"<br><strong>有效覆盖：</strong>{verdict.coverage_text}"
        "</div>"
    )
    passed_table = (
        f"<h3>通过用例（{len(verdict.passed)}）</h3>"
        '<table class="jujubit-summary"><thead><tr>'
        "<th>结果</th><th>用例</th></tr></thead><tbody>"
        f"{_simple_rows(verdict.passed)}</tbody></table>"
    )
    failed_table = (
        f"<h3>失败用例（{len(verdict.failed)}）</h3>"
        '<table class="jujubit-summary"><thead><tr>'
        "<th>结果与用例</th><th>页面与错误位置</th>"
        "<th>错误说明</th><th>截图与录像</th></tr></thead><tbody>"
        f"{_failure_rows(verdict.failed)}</tbody></table>"
    )
    unfinished_table = ""
    if verdict.unfinished:
        unfinished_table = (
            f"<h3>未完成 / 跳过用例（{len(verdict.unfinished)}，"
            f"其中因 HTTP 429 未完成 {verdict.rate_limited}）</h3>"
            '<table class="jujubit-summary"><thead><tr>'
            "<th>结果</th><th>用例</th><th>原因</th></tr></thead><tbody>"
            f"{_skipped_rows(verdict.unfinished)}</tbody></table>"
        )
    return _STYLE + banner + passed_table + failed_table + unfinished_table
