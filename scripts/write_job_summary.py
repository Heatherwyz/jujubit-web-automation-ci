#!/usr/bin/env python3
"""把本次运行结果渲染成 Markdown 摘要，输出到 stdout。

为什么需要：托管在 test-reports 分支的 HTML 报告无法在浏览器里渲染。GitHub 对
仓库内的 .html 一律返回 ``text/plain`` 并带 ``X-Content-Type-Options: nosniff``，
点开只能看到源码。私有仓库又不能用 Pages（需付费套餐，且内容公网可访问，而报告
含站点地址与失败详情）。

Job Summary 是唯一同时满足"浏览器直接渲染 + 受仓库权限保护 + 不额外付费"的位置，
它渲染 GitHub Flavored Markdown。本脚本只负责生成 Markdown 并打印，由工作流做
``>> "$GITHUB_STEP_SUMMARY"`` 重定向——脚本自身不打开任何来自环境变量的写入路径。

复用 send_lark_test_report 的解析逻辑，保证终端、飞书卡片、Job Summary 三个出口
口径一致。

用法：
    RESULTS_XML=artifacts/runs/<ts>/results.xml SUITE_LABEL=首页回归 \\
        python scripts/write_job_summary.py >> "$GITHUB_STEP_SUMMARY"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.send_lark_test_report import (  # noqa: E402  需先补 sys.path
    _business_failures,
    _format_duration,
    _ordinary_skipped,
    _rate_limited_unfinished,
    read_results,
)

# 未完成原因里出现这些字样时给出更具体的处置建议。
UNFINISHED_HINTS = (
    ("HTTP 429", "站点频控，等冷却后重跑；持续出现考虑固定出口 IP"),
    ("访问频控", "站点频控，等冷却后重跑"),
    ("人机验证", "CI 出口被拦截，需人工在可见浏览器完成验证"),
    ("登录态", "缺少有效登录态，检查 PLAYWRIGHT_STORAGE_STATE_JSON"),
    ("已知问题", "已登记的已知问题，按注释里的恢复条件处理"),
    ("未配置", "该模块在当前页面不存在，确认是否为预期"),
)


def resolve_results_path(raw_path: str) -> Path:
    """把结果文件路径限定在仓库目录内，拒绝 .. 穿越与符号链接逃逸。"""
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    resolved = candidate.resolve()
    repo_root = ROOT.resolve()
    if repo_root not in resolved.parents:
        raise SystemExit(f"结果文件必须位于仓库目录内，实际为 {resolved}")
    return resolved


def _verdict(summary: Dict[str, Any]) -> tuple[str, str]:
    """返回（结论文字, emoji）。业务失败优先于未完成。"""
    business_failures = _business_failures(summary)
    rate_limited = _rate_limited_unfinished(summary)
    ordinary_skipped = _ordinary_skipped(summary)
    total = int(summary.get("total", 0))

    if total == 0:
        return "未取得测试结果", "⚠️"
    if business_failures:
        return f"发现业务失败：{business_failures}/{total} 条", "❌"
    if rate_limited:
        return f"受站点频控影响：{rate_limited} 条未完成", "🟠"
    if ordinary_skipped:
        return f"执行完成，{ordinary_skipped} 条未完成", "🔵"
    return "全部通过", "✅"


def _hint_for(detail: str) -> str:
    for needle, hint in UNFINISHED_HINTS:
        if needle in detail:
            return hint
    return "打开报告查看具体原因"


def _coverage(summary: Dict[str, Any]) -> tuple[int, int, float]:
    """有效覆盖：真正得出业务结论的用例占计划用例的比例。"""
    total = int(summary.get("total", 0))
    passed = int(summary.get("passed", 0))
    executed = min(passed + _business_failures(summary), total)
    ratio = executed / total * 100 if total else 0.0
    return executed, total, ratio


def _cell(value: Any) -> str:
    """表格单元格转义，避免正文里的竖线破坏 Markdown 表格。"""
    text = str(value) if value not in (None, "") else "-"
    return text.replace("|", "\\|")


def build_summary(
    summary: Dict[str, Any],
    *,
    suite_label: str = "",
    report_url: str = "",
    index_url: str = "",
    run_id: str = "",
) -> str:
    """生成 Job Summary 的 Markdown。"""
    verdict, emoji = _verdict(summary)
    executed, total, ratio = _coverage(summary)
    business_failures = _business_failures(summary)
    rate_limited = _rate_limited_unfinished(summary)
    ordinary_skipped = _ordinary_skipped(summary)
    passed = int(summary.get("passed", 0))

    lines = [f"## {emoji} {verdict}", ""]
    if suite_label:
        lines += [
            f"**套件**：{suite_label}　　**运行标识**：`{run_id or '未知'}`",
            "",
        ]

    # 有效覆盖是判断这一轮可不可信的指标，放在最显眼处。
    lines += [
        "| 指标 | 数值 | 说明 |",
        "| --- | --- | --- |",
        f"| 有效覆盖 | **{ratio:.0f}%**（{executed}/{total}） | "
        "真正得出业务结论的用例占比，判断本轮可不可信 |",
        f"| 已执行通过率 | {passed}/{executed} | 站点功能是否正常 |",
        f"| 业务失败 | {business_failures} | 站点功能不符合预期，需立刻查 |",
        f"| 未完成 | {rate_limited + ordinary_skipped}"
        f"（429 {rate_limited} / 其他 {ordinary_skipped}） | "
        "没跑到断言，既不算通过也不算失败 |",
        f"| 耗时 | {_format_duration(summary.get('duration_seconds', 0))} | |",
        "",
    ]

    failed_cases = summary.get("failed_cases") or []
    if failed_cases:
        lines += [
            "### ❌ 业务失败",
            "",
            "| 模块 | 用例 | 错误 |",
            "| --- | --- | --- |",
        ]
        for case in failed_cases:
            lines.append(
                f"| {_cell(case.get('module'))} | `{_cell(case.get('name'))}` "
                f"| {_cell(case.get('detail'))} |"
            )
        lines.append("")

    unfinished = summary.get("unfinished_cases") or []
    if unfinished:
        lines += [
            "### ⏭ 未完成（未验证任何业务行为）",
            "",
            "| 模块 | 用例 | 原因 | 处置 |",
            "| --- | --- | --- | --- |",
        ]
        for case in unfinished:
            detail = str(case.get("detail", ""))
            lines.append(
                f"| {_cell(case.get('module'))} | `{_cell(case.get('name'))}` "
                f"| {_cell(detail)} | {_hint_for(detail)} |"
            )
        lines.append("")

    modules = summary.get("modules") or []
    if modules:
        lines += [
            "### 模块结果",
            "",
            "| 模块 | 通过 | 业务失败 | 未完成 |",
            "| --- | --- | --- | --- |",
        ]
        for module in modules:
            lines.append(
                f"| {_cell(module.get('name'))} | {int(module.get('passed', 0))} "
                f"| {_business_failures(module)} "
                f"| {_rate_limited_unfinished(module) + _ordinary_skipped(module)} |"
            )
        lines.append("")

    if report_url or index_url:
        lines += ["### 完整报告", ""]
        if report_url:
            lines.append(
                f"- [下载本次 HTML 报告]({report_url})"
                "（GitHub 不渲染仓库内 HTML，需下载后本地打开）"
            )
        if index_url:
            lines.append(f"- [历史报告索引]({index_url})")
        lines.append("")

    if rate_limited:
        lines += [
            "> HTTP 429 是站点访问频控，已单列为未完成，不与业务失败重复统计。",
            "",
        ]
    lines.append(
        "> 判断一轮回归是否可信看**有效覆盖**，不是通过率："
        "13 通过 + 17 未完成的通过率是 100%，但有效覆盖只有 43%。"
    )
    return "\n".join(lines)


def main() -> int:
    raw_results = os.getenv("RESULTS_XML", "").strip()
    if not raw_results:
        print("<!-- 未提供 RESULTS_XML，跳过测试摘要 -->")
        return 0

    results_path = resolve_results_path(raw_results)
    if not results_path.is_file():
        print(f"<!-- 结果文件不存在，跳过测试摘要：{results_path.name} -->")
        return 0

    summary = read_results(str(results_path))
    # 只写 stdout；由工作流重定向到 $GITHUB_STEP_SUMMARY。
    print(
        build_summary(
            summary,
            suite_label=os.getenv("SUITE_LABEL", "").strip(),
            report_url=os.getenv("REPORT_HTML_URL", "").strip(),
            index_url=os.getenv("REPORT_INDEX_URL", "").strip(),
            run_id=os.getenv("REPORT_RUN_ID", "").strip(),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
