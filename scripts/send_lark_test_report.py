"""向飞书群机器人发送 GitHub Actions 测试摘要。

脚本只从环境变量读取机器人 Webhook，不把密钥写进代码或报告。它解析 pytest
生成的 JUnit XML，区分业务失败与 HTTP 429 访问频控，再以飞书交互卡片发送摘要。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree


def parse_args() -> argparse.Namespace:
    """读取报告、GitHub 链接、时间戳和本次执行状态。"""
    parser = argparse.ArgumentParser(description="向飞书群发送 JuJuBit 自动化测试结果")
    parser.add_argument("--results-xml", default=os.getenv("RESULTS_XML", ""))
    parser.add_argument("--run-url", default=os.getenv("GITHUB_RUN_URL", ""))
    parser.add_argument("--artifact-url", default=os.getenv("REPORT_ARTIFACT_URL", ""))
    parser.add_argument("--run-id", default=os.getenv("REPORT_RUN_ID", ""))
    parser.add_argument("--exit-code", default=os.getenv("TEST_EXIT_CODE", ""))
    return parser.parse_args()


def read_results(results_xml: str) -> Dict[str, int]:
    """从 JUnit XML 汇总通过、失败、错误、跳过和 429 拦截数量。"""
    summary = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0, "rate_limited": 0}
    path = Path(results_xml) if results_xml else None
    if not path or not path.is_file():
        return summary

    root = ElementTree.parse(path).getroot()
    cases = root.findall(".//testcase")
    summary["total"] = len(cases)
    for case in cases:
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        detail = " ".join(
            value for value in (
                (failure.text if failure is not None else ""),
                (failure.get("message", "") if failure is not None else ""),
                (error.text if error is not None else ""),
                (error.get("message", "") if error is not None else ""),
                (skipped.text if skipped is not None else ""),
                (skipped.get("message", "") if skipped is not None else ""),
            ) if value
        )
        if failure is not None:
            summary["failed"] += 1
        elif error is not None:
            summary["errors"] += 1
        elif skipped is not None:
            summary["skipped"] += 1
        else:
            summary["passed"] += 1
        if "HTTP 429" in detail or "访问频控" in detail:
            summary["rate_limited"] += 1
    return summary


def card_template(
    summary: Dict[str, int],
    run_url: str,
    artifact_url: str,
    exit_code: str,
    run_id: str = "",
) -> Dict[str, object]:
    """生成包含 GitHub 运行记录和 HTML 报告下载入口的飞书卡片。"""
    business_failures = max(
        0, summary["failed"] + summary["errors"] - summary["rate_limited"]
    )
    if summary["total"] == 0:
        color, status = "orange", "未取得 JUnit 结果"
    elif business_failures > 0:
        color, status = "red", "发现业务失败"
    elif summary["rate_limited"] > 0:
        color, status = "orange", "被站点频控拦截"
    elif summary["skipped"] > 0:
        color, status = "blue", "执行完成（含跳过用例）"
    else:
        color, status = "green", "全部通过"

    fields = [
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**总用例**\n{summary['total']}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**通过**\n{summary['passed']}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**业务失败**\n{business_failures}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**429 频控**\n{summary['rate_limited']}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**跳过**\n{summary['skipped']}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**执行码**\n{exit_code or '未知'}"}},
    ]
    actions = []
    if run_url:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "打开 GitHub 执行记录"},
                "type": "primary",
                "url": run_url,
            }
        )
    if artifact_url:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "下载 HTML 报告与录像"},
                "type": "default",
                "url": artifact_url,
            }
        )
    run_label = f"\n运行标识：{run_id}" if run_id else ""
    elements = [
        {"tag": "div", "text": {"tag": "lark_md", "content": f"**状态：{status}**\n执行时间：{time.strftime('%Y-%m-%d %H:%M:%S %Z')}{run_label}"}},
        {"tag": "div", "fields": fields},
    ]
    if summary["rate_limited"]:
        elements.append(
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "HTTP 429 表示站点访问频控；这些 case 未实际执行，不应按页面功能缺陷处理。",
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
                "title": {"tag": "plain_text", "content": "JuJuBit 首页自动化测试"},
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
