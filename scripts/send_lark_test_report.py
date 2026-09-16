"""向飞书群机器人发送 GitHub Actions 测试摘要。

脚本只从环境变量读取机器人 Webhook，不把密钥写进代码或报告。它解析 pytest
生成的 JUnit XML，区分业务失败与 HTTP 429 访问频控，并按首页、购物车等业务模块
生成飞书交互卡片。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree


SUMMARY_KEYS = (
    "total",
    "passed",
    "failed",
    "errors",
    "skipped",
    "rate_limited",
    "rate_limited_skipped",
    "rate_limited_failures",
    "ordinary_skipped",
)
# 429 必须与 HTTP 语义相邻才算频控。此前用裸 \b429\b 匹配失败正文全文，
# 于是 traceback 的 "line 429"、"assert 429 == 430"、"resolved after 429 ms"
# 都会把真实业务失败改判成"受站点频控影响"，卡片从红降级成橙。
# traceback 里出现 429 行号是完全正常的事，不能作为频控证据。
RATE_LIMIT_PATTERN = re.compile(
    r"""
      http\s*/?\d*(?:\.\d+)?\s*429\b   # HTTP 429 / HTTP/1.1 429
    | \b429\s*(?:too\s+many\s+requests|frequency|rate)  # 429 Too Many Requests
    | (?:status(?:_code)?|code|响应|返回)\s*[=:：]?\s*429\b  # status=429 / 返回 429
    # 反向：pytest 会把断言展开成 "429 = <Response ...>.status"，
    # 这是真实的 429 断言失败（历史 artifacts 里出现过），必须识别。
    | \b429\s*=\s*[^\n]{0,100}?\.status\b
    | 访问频控
    | 频率限制
    | rate[ _-]?limit(?:ed|ing)?
    | too\s+many\s+requests
    | retry[- ]after
    """,
    re.I | re.X,
)
MODULE_ORDER = {"首页": 0, "购物车": 1, "其他": 99}
MODULE_PATTERNS = {
    "首页": re.compile(r"(?:^|[^a-z0-9])(?:home|homepage)(?:$|[^a-z0-9])|首页", re.I),
    "购物车": re.compile(
        r"(?:^|[^a-z0-9])(?:cart|shopping[_-]?cart|shoppingcart)(?:$|[^a-z0-9])|购物车",
        re.I,
    ),
}

# 购物车工作流传入 machine-readable 的 suite 值；卡片中始终展示面向业务的中文范围。
SUITE_LABELS = {
    "smoke": "Smoke：PC 主链路 1 条",
    "daily": "每日分层：PC 15 条 + H5 关键 6 条",
    "full": "完整回归：PC 15 条 + H5 15 条",
}


def parse_args() -> argparse.Namespace:
    """读取报告、GitHub 链接、执行元信息和本次测试状态。"""
    parser = argparse.ArgumentParser(description="向飞书群发送 JuJuBit 自动化测试结果")
    parser.add_argument("--results-xml", default=os.getenv("RESULTS_XML", ""))
    parser.add_argument("--run-url", default=os.getenv("GITHUB_RUN_URL", ""))
    parser.add_argument("--artifact-url", default=os.getenv("REPORT_ARTIFACT_URL", ""))
    parser.add_argument(
        "--report-html-url", default=os.getenv("REPORT_HTML_URL", "")
    )
    parser.add_argument("--run-id", default=os.getenv("REPORT_RUN_ID", ""))
    parser.add_argument("--exit-code", default=os.getenv("TEST_EXIT_CODE", ""))
    parser.add_argument(
        "--branch",
        default=(
            os.getenv("TEST_BRANCH", "")
            or os.getenv("GITHUB_HEAD_REF", "")
            or os.getenv("GITHUB_REF_NAME", "")
        ),
    )
    parser.add_argument(
        "--actor",
        default=os.getenv("TEST_ACTOR", "") or os.getenv("GITHUB_ACTOR", ""),
    )
    parser.add_argument(
        "--commit",
        default=os.getenv("TEST_COMMIT", "") or os.getenv("GITHUB_SHA", ""),
    )
    parser.add_argument("--started-at", default=os.getenv("TEST_STARTED_AT", ""))
    parser.add_argument(
        "--suite",
        default=os.getenv("TEST_SUITE", ""),
        help="本次购物车执行套件：smoke、daily 或 full。",
    )
    parser.add_argument(
        "--suite-label",
        default=os.getenv("TEST_SUITE_LABEL", ""),
        help="工作流传入的中文执行范围说明。",
    )
    parser.add_argument(
        "--planned-cases",
        default=os.getenv("TEST_PLANNED_CASES", ""),
        help="工作流计划执行的用例数。",
    )
    parser.add_argument(
        "--actual-cases",
        default=os.getenv("TEST_ACTUAL_CASES", ""),
        help="工作流从 JUnit XML 统计出的实际收集用例数。",
    )
    return parser.parse_args()


def _empty_counts() -> Dict[str, int]:
    """创建一组独立计数器，供总计和各模块复用。"""
    return {key: 0 for key in SUMMARY_KEYS}


def _empty_summary() -> Dict[str, Any]:
    """在 XML 缺失或解析失败时返回仍可生成卡片的空结果。"""
    return {
        **_empty_counts(),
        "duration_seconds": 0.0,
        "started_at": "",
        "modules": [],
        "failed_cases": [],
        "unfinished_cases": [],
    }


def _skip_reason(case: ElementTree.Element, *, max_length: int = 120) -> str:
    """取跳过原因。pytest 把它放在 skipped 节点的 message 属性里。"""
    for child in case:
        if child.tag.rsplit("}", 1)[-1] != "skipped":
            continue
        text = (child.get("message") or child.text or "").strip()
        if text:
            return re.sub(r"\s+", " ", text)[:max_length]
    return ""


def _case_detail(case: ElementTree.Element, *, max_length: int = 120) -> str:
    """取失败用例的一行错误摘要，供卡片直接展示。"""
    for child in case:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag not in {"failure", "error"}:
            continue
        text = (child.get("message") or child.text or "").strip()
        if not text:
            continue
        # 折叠换行与多余空白；pytest 的 longrepr 往往很长。
        flat = re.sub(r"\s+", " ", text)
        return flat[:max_length]
    return ""


def _elements(root: ElementTree.Element, name: str) -> Iterable[ElementTree.Element]:
    """兼容带或不带 XML namespace 的 JUnit 节点。"""
    return (element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == name)


def _safe_seconds(value: str) -> float:
    """JUnit 的 time 字段异常时按 0 秒处理，避免通知脚本再次失败。"""
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _matches_module(value: str, module: str) -> bool:
    """识别测试文件、类名或用例名中的业务模块标识。"""
    return bool(MODULE_PATTERNS[module].search(value.replace("\\", "/")))


def module_for_case(case: ElementTree.Element) -> str:
    """根据 JUnit 的 classname、file 和 name 归类业务模块。

    文件或类名的权重高于用例名。例如首页中的“购物车入口”用例仍属于首页；未来
    ``test_cart.py``、``TestCart`` 或名称含 ``shopping_cart`` 的用例会归到购物车。
    """
    owner = " ".join((case.get("classname", ""), case.get("file", ""))).lower()
    case_name = case.get("name", "").lower()
    # 文件/类所属模块优先：例如首页里的“购物车入口”用例即使函数名含 cart，
    # 仍然应归在“首页”；只有真正的购物车文件/类才归入“购物车”。
    for module in ("首页", "购物车"):
        if _matches_module(owner, module):
            return module
    for module in ("购物车", "首页"):
        if _matches_module(case_name, module):
            return module
    # 当前仓库只有首页用例；无法识别的新文件单独列为“其他”，避免错误并入首页。
    return "其他"


def _case_result(case: ElementTree.Element) -> tuple[str, bool]:
    """返回用例结果类别，以及失败内容是否属于 HTTP 429 访问频控。"""
    children = {
        child.tag.rsplit("}", 1)[-1]: child
        for child in case
        if child.tag.rsplit("}", 1)[-1] in {"failure", "error", "skipped"}
    }
    if "failure" in children:
        outcome = "failed"
    elif "error" in children:
        outcome = "errors"
    elif "skipped" in children:
        outcome = "skipped"
    else:
        outcome = "passed"

    detail_parts = []
    for child in children.values():
        detail_parts.extend((child.text or "", child.get("message", "")))
    detail = " ".join(part for part in detail_parts if part)
    return outcome, bool(RATE_LIMIT_PATTERN.search(detail))


def _suite_duration(root: ElementTree.Element, cases: list[ElementTree.Element]) -> float:
    """优先使用 JUnit testsuite 总耗时，没有时再累加用例耗时。"""
    if root.tag.rsplit("}", 1)[-1] == "testsuite":
        suite_seconds = _safe_seconds(root.get("time", ""))
        if suite_seconds:
            return suite_seconds

    direct_suites = [
        child for child in root if child.tag.rsplit("}", 1)[-1] == "testsuite"
    ]
    suite_seconds = sum(_safe_seconds(suite.get("time", "")) for suite in direct_suites)
    if suite_seconds:
        return suite_seconds
    return sum(_safe_seconds(case.get("time", "")) for case in cases)


def read_results(results_xml: str) -> Dict[str, Any]:
    """从 JUnit XML 汇总结果、耗时、开始时间和业务模块。"""
    summary = _empty_summary()
    path = Path(results_xml) if results_xml else None
    if not path or not path.is_file():
        return summary

    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError):
        return summary

    cases = list(_elements(root, "testcase"))
    summary["total"] = len(cases)
    modules: Dict[str, Dict[str, Any]] = {}
    for case in cases:
        outcome, rate_limited = _case_result(case)
        summary[outcome] += 1
        if rate_limited:
            summary["rate_limited"] += 1
            if outcome == "skipped":
                summary["rate_limited_skipped"] += 1
            elif outcome in {"failed", "errors"}:
                summary["rate_limited_failures"] += 1
        elif outcome == "skipped":
            summary["ordinary_skipped"] += 1

        module_name = module_for_case(case)
        module = modules.setdefault(
            module_name,
            {
                "name": module_name,
                **_empty_counts(),
                "duration_seconds": 0.0,
            },
        )
        module["total"] += 1
        module[outcome] += 1
        module["duration_seconds"] += _safe_seconds(case.get("time", ""))
        if rate_limited:
            module["rate_limited"] += 1
            if outcome == "skipped":
                module["rate_limited_skipped"] += 1
            elif outcome in {"failed", "errors"}:
                module["rate_limited_failures"] += 1
        elif outcome == "skipped":
            module["ordinary_skipped"] += 1

        # 记录业务失败的用例名，让卡片能直接回答"失败的是什么"，
        # 不必点开报告或翻 Actions 日志。已确认的 429 频控不算业务失败。
        if outcome in {"failed", "errors"} and not rate_limited:
            summary["failed_cases"].append(
                {
                    "name": case.get("name", "") or "未知用例",
                    "module": module_name,
                    "detail": _case_detail(case),
                }
            )
        # 未完成同样要能追溯：跳过原因决定了这一轮该不该重跑，
        # 以及是环境问题还是已登记的已知问题。
        elif outcome == "skipped" or (
            outcome in {"failed", "errors"} and rate_limited
        ):
            summary["unfinished_cases"].append(
                {
                    "name": case.get("name", "") or "未知用例",
                    "module": module_name,
                    "detail": _case_detail(case) or _skip_reason(case),
                }
            )

    suites = list(_elements(root, "testsuite"))
    summary["duration_seconds"] = _suite_duration(root, cases)
    summary["started_at"] = next(
        (suite.get("timestamp", "") for suite in suites if suite.get("timestamp")),
        "",
    )
    summary["modules"] = sorted(
        modules.values(),
        key=lambda item: (MODULE_ORDER.get(item["name"], 50), item["name"]),
    )
    return summary


def _business_failures(summary: Dict[str, Any]) -> int:
    """从失败与错误中剔除已确认的 HTTP 429 访问频控。"""
    failed_or_error = int(summary.get("failed", 0)) + int(summary.get("errors", 0))
    if "rate_limited_failures" in summary:
        rate_limited_failures = int(summary["rate_limited_failures"])
    else:
        # 旧报告没有细分字段。此时不能直接拿 rate_limited 相减：429 多数表现为
        # skipped，rate_limited 会远大于失败数（如 1 失败 - 17 频控 = 0），
        # 真实业务失败会被静默清零，卡片还会从红降级成橙。改为先扣除已知的
        # 429 跳过数，剩下的才可能是以 failure 形式记录的频控。
        rate_limited = int(summary.get("rate_limited", 0))
        rate_limited_skipped = summary.get("rate_limited_skipped")
        if rate_limited_skipped is None:
            rate_limited_skipped = min(int(summary.get("skipped", 0)), rate_limited)
        rate_limited_failures = max(0, rate_limited - int(rate_limited_skipped))
    # 上限同样不能超过实际失败数，避免任何情况下把业务失败抹平为 0。
    rate_limited_failures = min(rate_limited_failures, failed_or_error)
    return max(0, failed_or_error - rate_limited_failures)


def _rate_limited_unfinished(summary: Dict[str, Any]) -> int:
    """返回因站点 429 未完成的互斥用例数，兼容旧报告中的 error 记录。"""
    return int(summary.get("rate_limited", 0))


def _ordinary_skipped(summary: Dict[str, Any]) -> int:
    """返回非 429 原因的跳过数；旧格式则从总跳过数中反推。"""
    skipped = int(summary.get("skipped", 0))
    if "ordinary_skipped" not in summary:
        # 旧版 XML 汇总没有细分字段；429 若本身就是 skipped，先从总跳过中扣除，
        # 避免历史报告在卡片里被重复展示为“429 未完成”和“其他跳过”。
        rate_limited_skipped = summary.get("rate_limited_skipped")
        if rate_limited_skipped is None:
            rate_limited_skipped = min(skipped, int(summary.get("rate_limited", 0)))
        return max(0, skipped - int(rate_limited_skipped))
    return max(
        0,
        int(summary["ordinary_skipped"]),
    )


def _format_duration(seconds: Any) -> str:
    """把秒数转换为适合群消息快速阅读的中文耗时。"""
    total_seconds = int(round(_safe_seconds(str(seconds))))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}时{minutes}分{seconds}秒"
    if minutes:
        return f"{minutes}分{seconds}秒"
    return f"{seconds}秒"


def _display_value(value: str, fallback: str = "未知", max_length: int = 80) -> str:
    """清理 GitHub 元信息中的换行和 Markdown 定界符，避免卡片排版被破坏。"""
    cleaned = " ".join((value or "").replace("`", "'").split())
    if not cleaned:
        return fallback
    return cleaned[:max_length]


def _format_started_at(value: str) -> str:
    """将 JUnit ISO 时间压缩为无微秒、便于阅读的格式。"""
    cleaned = _display_value(value)
    if cleaned == "未知":
        return cleaned
    # 仅替换 ISO 8601 日期和时间之间的 T；不能误改时区缩写 CST 中的 T。
    cleaned = re.sub(r"(?<=\d)T(?=\d)", " ", cleaned, count=1)
    # JUnit 时间通常带六位微秒；群通知不需要展示这一精度。
    return re.sub(r"(?<=\d)\.\d+(?=(?:Z|[+-]\d{2}:?\d{2})?$)", "", cleaned)


def _case_count(value: str | int, fallback: str = "未标注") -> str:
    """把工作流输出的用例数清理成可读文本，避免卡片展示空值或注入内容。"""
    cleaned = str(value or "").strip()
    if cleaned.isdigit():
        return f"{int(cleaned)} 条"
    return fallback


def _known_case_count(value: str | int) -> int | None:
    """仅把明确的非负整数识别为已知用例数。"""
    cleaned = str(value or "").strip()
    return int(cleaned) if cleaned.isdigit() else None


def _case_count_mismatch(summary: Dict[str, Any], planned_cases: str | int) -> bool:
    """判断已有 JUnit 结果是否少于或多于工作流计划数。"""
    total = int(summary.get("total", 0))
    planned = _known_case_count(planned_cases)
    # total=0 继续交给“未取得测试结果”或“测试进程异常”逻辑处理。
    return total > 0 and planned is not None and planned != total


def _suite_execution_lines(
    summary: Dict[str, Any],
    suite: str,
    suite_label: str,
    planned_cases: str,
    actual_cases: str,
) -> str:
    """生成套件范围及计划/实际数，实际数优先使用已解析的 JUnit 结果。"""
    normalized_suite = str(suite or "").strip().lower()
    label = _display_value(suite_label, fallback="")
    if not label:
        label = SUITE_LABELS.get(normalized_suite, "默认回归（未单独标注套件）")

    planned = _case_count(planned_cases)
    # JUnit 的 testcase 总数是本次真正进入结果报告的权威数据；工作流传值仅作为
    # XML 未生成时的兜底，避免步骤异常时把计划数误写成实际执行数。
    total = int(summary.get("total", 0))
    actual = _case_count(total, fallback="") if total else ""
    if not actual:
        actual = _case_count(actual_cases, fallback="未生成结果")
    mismatch_label = " **（计划与实际不一致）**" if _case_count_mismatch(
        summary, planned_cases
    ) else ""
    return (
        f"**执行套件**　{label}\n"
        f"**计划 / 实际执行**　{planned} / {actual}{mismatch_label}"
    )


def _failed_case_lines(summary: Dict[str, Any], *, limit: int = 8) -> str:
    """生成“失败用例”列表，每行是用例名加一句错误摘要。

    卡片原先只显示"业务失败 1"，必须点开报告才知道失败的是什么。这里直接给出
    用例名与原因；超过 limit 条时截断并提示看报告，避免卡片过长。
    """
    cases = summary.get("failed_cases") or []
    if not cases:
        return ""
    lines = []
    for case in cases[:limit]:
        name = _display_value(str(case.get("name", "")), max_length=80)
        module = str(case.get("module", "")).strip()
        prefix = f"[{module}] " if module and module != "其他" else ""
        detail = str(case.get("detail", "")).strip()
        line = f"- {prefix}`{name}`"
        if detail:
            line += f"\n  {detail}"
        lines.append(line)
    remaining = len(cases) - limit
    if remaining > 0:
        lines.append(f"- 另有 {remaining} 条失败，详见 HTML 报告")
    return "\n".join(lines)


def _module_lines(summary: Dict[str, Any]) -> str:
    """生成“模块结果”列表；首页固定排在购物车之前。"""
    modules = summary.get("modules") or []
    if not modules and int(summary.get("total", 0)):
        modules = [
            {
                "name": "首页",
                **{key: int(summary.get(key, 0)) for key in SUMMARY_KEYS},
                "duration_seconds": summary.get("duration_seconds", 0),
            }
        ]
    if not modules:
        return "暂无模块结果"

    lines = []
    for module in modules:
        business_failures = _business_failures(module)
        rate_limited = _rate_limited_unfinished(module)
        ordinary_skipped = _ordinary_skipped(module)
        if business_failures:
            state = "失败"
        elif rate_limited:
            state = "受频控影响"
        elif ordinary_skipped:
            state = "含跳过"
        else:
            state = "通过"
        details = [
            f"通过 {int(module.get('passed', 0))}/{int(module.get('total', 0))}",
            _format_duration(module.get("duration_seconds", 0)),
        ]
        if business_failures:
            details.append(f"业务失败 {business_failures}")
        if rate_limited:
            details.append(f"429 未完成 {rate_limited}")
        if ordinary_skipped:
            details.append(f"其他跳过 {ordinary_skipped}")
        lines.append(
            f"**{state}｜{module['name']}**　" + " · ".join(details)
        )
    return "\n".join(lines)


def card_template(
    summary: Dict[str, Any],
    run_url: str = "",
    artifact_url: str = "",
    report_html_url: str = "",
    exit_code: str = "",
    run_id: str = "",
    branch: str = "",
    actor: str = "",
    commit: str = "",
    started_at: str = "",
    suite: str = "",
    suite_label: str = "",
    planned_cases: str = "",
    actual_cases: str = "",
) -> Dict[str, object]:
    """生成包含执行信息、模块结果和报告入口的飞书卡片。"""
    total = int(summary.get("total", 0))
    passed = int(summary.get("passed", 0))
    rate_limited = _rate_limited_unfinished(summary)
    ordinary_skipped = _ordinary_skipped(summary)
    business_failures = _business_failures(summary)
    case_count_mismatch = _case_count_mismatch(summary, planned_cases)
    normalized_exit_code = str(exit_code).strip()
    # pytest 的 1 表示“用例有失败”，已由 JUnit 明细解释；2~5 才是进程级异常。
    abnormal_exit = bool(normalized_exit_code and normalized_exit_code not in {"0", "1"})
    if business_failures > 0:
        color, status = "red", "发现业务失败"
    elif abnormal_exit:
        color, status = "red", "测试进程异常"
    elif total == 0:
        color, status = "orange", "未取得测试结果"
    elif case_count_mismatch:
        color, status = "orange", "计划与实际用例数不一致"
    elif rate_limited > 0:
        color, status = "orange", "受站点频控影响"
    elif ordinary_skipped > 0:
        color, status = "blue", "执行完成（含跳过用例）"
    else:
        color, status = "green", "全部通过"

    # 失败与未完成是两个口径。未完成的用例没有验证任何业务行为，既不能算通过，
    # 也不能算失败：把它留在“通过率”分母里会让 0 业务失败的一轮显示成大量不通过，
    # 把它从分母剔除又会让 13/30 显示成 100%。因此显式给出两个数——
    # 已执行用例的通过率（判断站点好坏）和有效覆盖（判断本轮可不可信）。
    #
    # 分母用正向口径 passed + business_failures，即"真正得出业务结论的用例"。
    # 原先写成 total - (rate_limited + ordinary_skipped)：rate_limited 含以
    # failure 形式记录的 429，而那些用例本来就不在 passed 里，分母被过度扣减，
    # 旧格式报告曾算出 450%（total=10 passed=9 failed=1 rate_limited=8）。
    executed = passed + business_failures
    # 兜底防御：任何计数异常都不该让比率越界或出现负数分母。
    executed = max(0, min(executed, total))
    unfinished = max(0, total - executed)
    executed_pass_rate = (passed / executed * 100) if executed else 0.0
    executed_pass_rate = min(executed_pass_rate, 100.0)
    coverage = (executed / total * 100) if total else 0.0
    fields = [
        {
            "is_short": True,
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**已执行通过率**\n{executed_pass_rate:.1f}%（{passed}/{executed}）"
                ),
            },
        },
        {
            "is_short": True,
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**有效覆盖**\n{coverage:.0f}%（{executed}/{total} 条得出结论）"
                ),
            },
        },
        {
            "is_short": True,
            "text": {
                "tag": "lark_md",
                "content": f"**业务失败**\n{business_failures}",
            },
        },
        {
            "is_short": True,
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**429 未完成 / 其他跳过**\n"
                    f"{rate_limited} / {ordinary_skipped}"
                ),
            },
        },
        {
            "is_short": True,
            "text": {
                "tag": "lark_md",
                "content": f"**耗时**\n{_format_duration(summary.get('duration_seconds', 0))}",
            },
        },
    ]
    actions = []
    # HTML 报告直链放在最前且用 primary：它是排查失败时最先要看的东西，
    # 不用再下载 artifact 或翻 Actions 页面。
    # 运行页放第一个且为主按钮：Job Summary 在那里，是唯一能在浏览器直接读的
    # 完整结论（GitHub 对仓库内 HTML 强制 text/plain + nosniff，不渲染）。
    if run_url:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "查看运行摘要"},
                "type": "primary",
                "url": run_url,
            }
        )
    if report_html_url:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "下载 HTML 报告"},
                "type": "default",
                "url": report_html_url,
            }
        )
    if artifact_url:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "下载报告与录屏"},
                "type": "default",
                "url": artifact_url,
            }
        )
    commit_label = _display_value(commit, max_length=40)
    if commit_label != "未知":
        commit_label = commit_label[:7]
    started_label = _format_started_at(started_at or str(summary.get("started_at", "")))
    execution_info = (
        f"**分支**　{_display_value(branch)}　　"
        f"**执行人**　{_display_value(actor)}\n"
        f"**提交**　`{commit_label}`　　"
        f"**开始时间**　{started_label}"
    )
    if run_id:
        execution_info += f"\n**运行标识**　{_display_value(run_id)}"
    execution_scope = _suite_execution_lines(
        summary, suite, suite_label, planned_cases, actual_cases
    )
    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**状态：{status}**　　总用例：{total}",
            },
        },
        {"tag": "div", "fields": fields},
        {"tag": "hr"},
        {"tag": "div", "text": {"tag": "lark_md", "content": execution_scope}},
        {"tag": "hr"},
        {"tag": "div", "text": {"tag": "lark_md", "content": execution_info}},
        {"tag": "hr"},
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**模块结果**\n{_module_lines(summary)}",
            },
        },
    ]
    # 直接列出失败用例名与错误摘要：卡片原先只给"业务失败 1"，还得点开报告
    # 才知道是哪条。这是排查时第一个要看的信息。
    failure_lines = _failed_case_lines(summary)
    if failure_lines:
        elements.insert(
            2,
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**失败用例**\n{failure_lines}",
                },
            },
        )
    if rate_limited:
        elements.append(
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "HTTP 429 表示站点访问频控；该项已单列为“429 未完成”，不与业务失败或其他跳过重复统计。",
                    }
                ],
            }
        )
    if case_count_mismatch:
        planned = _known_case_count(planned_cases)
        elements.append(
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": (
                            f"计划与实际不一致：计划执行 {planned} 条，"
                            f"JUnit 实际生成 {total} 条。请检查用例收集、筛选条件或执行中断情况。"
                        ),
                    }
                ],
            }
        )
    if actions:
        elements.append({"tag": "action", "actions": actions})
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": color,
                "title": {
                    "tag": "plain_text",
                    "content": f"JuJuBit 自动化测试 · {status}",
                },
            },
            "elements": elements,
        },
    }


def sign_payload(payload: Dict[str, object], secret: str) -> Dict[str, object]:
    """机器人启用签名校验时，按飞书要求附加 timestamp 与 HMAC 签名。"""
    if not secret:
        return payload
    timestamp = str(int(time.time()))
    digest = hmac.new(
        f"{timestamp}\n{secret}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    signed = dict(payload)
    signed["timestamp"] = timestamp
    signed["sign"] = base64.b64encode(digest).decode("utf-8")
    return signed


# 自定义机器人 Webhook 只会挂在飞书/Lark 的官方域名下。限定 scheme 与 host
# 后，配错或被篡改的 LARK_WEBHOOK_URL 无法让本脚本把测试报告（含站点地址、
# 失败详情）POST 到任意第三方或内网地址。
ALLOWED_WEBHOOK_HOSTS = (
    "open.feishu.cn",
    "open.larksuite.com",
    "open.larkoffice.com",
)


class _NoRedirect(HTTPRedirectHandler):
    """拒绝任何重定向，确保报告正文只发往已校验的飞书域名。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError(
            f"飞书 Webhook 返回了重定向（HTTP {code} -> {newurl}）；"
            "为避免把测试报告投递到未校验的地址，已拒绝跟随。"
        )


def _validate_webhook_url(webhook_url: str) -> str:
    """校验 Webhook 为 HTTPS 且指向飞书官方域名，避免请求被重定向到任意地址。"""
    try:
        parts = urlsplit(webhook_url)
    except ValueError as error:
        raise RuntimeError(f"LARK_WEBHOOK_URL 不是合法 URL：{error}") from error
    if parts.scheme != "https":
        raise RuntimeError(
            f"LARK_WEBHOOK_URL 必须使用 https，当前为 {parts.scheme or '空'}。"
        )
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in ALLOWED_WEBHOOK_HOSTS:
        raise RuntimeError(
            "LARK_WEBHOOK_URL 的域名不在飞书官方允许列表内："
            f"{host or '空'}；允许 {', '.join(ALLOWED_WEBHOOK_HOSTS)}。"
        )
    return webhook_url


def post_to_lark(webhook_url: str, payload: Dict[str, object]) -> None:
    """发送 JSON 卡片，并检查飞书 HTTP 200 响应中的业务错误码。"""
    request = Request(
        _validate_webhook_url(webhook_url),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    # 禁止跟随重定向：否则一个域名合规的 Webhook 仍可能把报告正文重定向投递到
    # 内网或第三方地址。飞书自定义机器人正常不会返回 3xx。
    opener = build_opener(_NoRedirect)
    with opener.open(request, timeout=20) as response:
        body = response.read().decode("utf-8", errors="replace")
        if response.status >= 300:
            raise RuntimeError(f"飞书机器人返回 HTTP {response.status}")
        if not body.strip():
            return
        try:
            result = json.loads(body)
        except json.JSONDecodeError as error:
            raise RuntimeError("飞书机器人返回了无法解析的响应") from error
        # 自定义机器人可能使用 code，也可能使用旧版 StatusCode 字段。
        response_code = result.get("code")
        if response_code is None:
            response_code = result.get("StatusCode")
        if response_code is not None and str(response_code) != "0":
            response_message = result.get("msg", result.get("StatusMessage", "未知错误"))
            raise RuntimeError(
                f"飞书机器人业务返回失败：code={response_code}，消息={response_message}"
            )


def main() -> int:
    """解析结果并发送通知；未配置 Webhook 时安全跳过。"""
    args = parse_args()
    webhook_url = os.getenv("LARK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("未配置 LARK_WEBHOOK_URL，跳过飞书通知。")
        return 0
    summary = read_results(args.results_xml)
    payload = card_template(
        summary,
        args.run_url,
        args.artifact_url,
        args.report_html_url,
        args.exit_code,
        args.run_id,
        args.branch,
        args.actor,
        args.commit,
        args.started_at,
        args.suite,
        args.suite_label,
        args.planned_cases,
        args.actual_cases,
    )
    payload = sign_payload(payload, os.getenv("LARK_WEBHOOK_SECRET", ""))
    try:
        post_to_lark(webhook_url, payload)
    except (HTTPError, URLError, RuntimeError) as error:
        print(f"飞书通知发送失败：{error}", file=sys.stderr)
        return 1
    print("飞书测试摘要已发送。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
