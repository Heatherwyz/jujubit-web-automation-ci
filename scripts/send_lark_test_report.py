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
from urllib.request import Request, urlopen
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
RATE_LIMIT_PATTERN = re.compile(
    r"(?:\bhttp\s*)?\b429\b|访问频控|rate[ -]?limit(?:ed|ing)?|too many requests",
    re.I,
)
MODULE_ORDER = {"首页": 0, "购物车": 1, "其他": 99}
MODULE_PATTERNS = {
    "首页": re.compile(r"(?:^|[^a-z0-9])(?:home|homepage)(?:$|[^a-z0-9])|首页", re.I),
    "购物车": re.compile(
        r"(?:^|[^a-z0-9])(?:cart|shopping[_-]?cart|shoppingcart)(?:$|[^a-z0-9])|购物车",
        re.I,
    ),
}


def parse_args() -> argparse.Namespace:
    """读取报告、GitHub 链接、执行元信息和本次测试状态。"""
    parser = argparse.ArgumentParser(description="向飞书群发送 JuJuBit 自动化测试结果")
    parser.add_argument("--results-xml", default=os.getenv("RESULTS_XML", ""))
    parser.add_argument("--run-url", default=os.getenv("GITHUB_RUN_URL", ""))
    parser.add_argument("--artifact-url", default=os.getenv("REPORT_ARTIFACT_URL", ""))
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
    }


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
    rate_limited_failures = int(
        summary.get("rate_limited_failures", summary.get("rate_limited", 0))
    )
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
    exit_code: str = "",
    run_id: str = "",
    branch: str = "",
    actor: str = "",
    commit: str = "",
    started_at: str = "",
) -> Dict[str, object]:
    """生成包含执行信息、模块结果和报告入口的飞书卡片。"""
    total = int(summary.get("total", 0))
    passed = int(summary.get("passed", 0))
    rate_limited = _rate_limited_unfinished(summary)
    ordinary_skipped = _ordinary_skipped(summary)
    business_failures = _business_failures(summary)
    normalized_exit_code = str(exit_code).strip()
    # pytest 的 1 表示“用例有失败”，已由 JUnit 明细解释；2~5 才是进程级异常。
    abnormal_exit = bool(normalized_exit_code and normalized_exit_code not in {"0", "1"})
    if business_failures > 0:
        color, status = "red", "发现业务失败"
    elif abnormal_exit:
        color, status = "red", "测试进程异常"
    elif total == 0:
        color, status = "orange", "未取得测试结果"
    elif rate_limited > 0:
        color, status = "orange", "受站点频控影响"
    elif ordinary_skipped > 0:
        color, status = "blue", "执行完成（含跳过用例）"
    else:
        color, status = "green", "全部通过"

    pass_rate = (passed / total * 100) if total else 0.0
    fields = [
        {
            "is_short": True,
            "text": {
                "tag": "lark_md",
                "content": f"**执行通过率**\n{pass_rate:.1f}%（{passed}/{total}）",
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
    if run_url:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "查看运行与报告"},
                "type": "primary",
                "url": run_url,
            }
        )
    if artifact_url:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "下载 HTML 报告与录屏"},
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


def post_to_lark(webhook_url: str, payload: Dict[str, object]) -> None:
    """发送 JSON 卡片，并检查飞书 HTTP 200 响应中的业务错误码。"""
    request = Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
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
        args.exit_code,
        args.run_id,
        args.branch,
        args.actor,
        args.commit,
        args.started_at,
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
