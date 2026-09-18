#!/usr/bin/env python3
"""GitHub ``schedule`` 迟到后，若本机已经 ``workflow_dispatch`` 过则跳过。

GitHub 对本仓库的 cron 长期晚 4–5 小时。本机 LaunchAgent / crontab 会在北京时间
09:00 / 21:00 准时 ``gh workflow run``。如果迟到的 ``schedule`` 仍执行，购物车会
被同一班次跑两遍（真实生成、写入账号）。

本脚本**不发起网络请求**。工作流用 ``gh api`` 把最近的 ``workflow_dispatch``
列表写到 JSON，再交给这里判断。非 ``schedule`` 事件永不跳过；JSON 读失败则
fail-open（``skip=false``），让备份定时仍能跑。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


ALLOWED_WORKFLOW_FILES = frozenset(
    {
        "daily-ui-tests.yml",
        "cart-ui-tests.yml",
        "offline-checks.yml",
    }
)
DEFAULT_WINDOW_HOURS = 11
DEFAULT_REF = "main"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析工作流文件名、去重窗口和本地 JSON 路径。"""
    parser = argparse.ArgumentParser(description="迟到的 GitHub schedule 是否应跳过")
    parser.add_argument(
        "--workflow-file",
        required=True,
        help="工作流文件名，必须是仓库内三个 YAML 之一",
    )
    parser.add_argument(
        "--runs-json",
        default="",
        help="gh api 返回的 workflow runs JSON 文件路径；不发起网络请求",
    )
    parser.add_argument(
        "--window-hours",
        type=int,
        default=DEFAULT_WINDOW_HOURS,
        help="向前看多少小时内的 workflow_dispatch（默认 11，盖住 4–5 小时迟到且不跨班）",
    )
    parser.add_argument(
        "--ref",
        default=os.getenv("GITHUB_REF_NAME", DEFAULT_REF),
        help="只对这一分支的手动触发去重，默认 main",
    )
    return parser.parse_args(argv)


def require_allowed_workflow(workflow_file: str) -> str:
    """只接受仓库内三个工作流文件名。"""
    name = Path(workflow_file.strip()).name
    if name not in ALLOWED_WORKFLOW_FILES:
        raise ValueError(
            f"拒绝未知工作流文件 {workflow_file!r}，允许："
            + ", ".join(sorted(ALLOWED_WORKFLOW_FILES))
        )
    return name


def parse_github_datetime(value: str) -> datetime:
    """解析 GitHub API 的 UTC 时间戳。"""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def should_skip_runs(
    runs: Iterable[dict[str, Any]],
    *,
    now: datetime,
    window_hours: int,
    ref: str,
) -> bool:
    """窗口内已有同分支的 workflow_dispatch（未取消）则应跳过。"""
    if window_hours <= 0:
        raise ValueError(f"window_hours 必须为正整数，当前为 {window_hours}")
    cutoff = now - timedelta(hours=window_hours)
    for run in runs:
        created_raw = run.get("created_at") or ""
        try:
            created = parse_github_datetime(str(created_raw))
        except ValueError:
            continue
        if created < cutoff:
            continue
        event = str(run.get("event") or "")
        if event and event != "workflow_dispatch":
            continue
        head_branch = run.get("head_branch") or ""
        if head_branch and head_branch != ref:
            continue
        if run.get("status") == "cancelled" or run.get("conclusion") == "cancelled":
            continue
        return True
    return False


def load_runs(path: Path) -> list[dict[str, Any]]:
    """读取 gh api 的 workflow runs JSON。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        runs = payload
    elif isinstance(payload, dict):
        runs = payload.get("workflow_runs") or []
    else:
        raise ValueError("runs JSON 必须是对象或列表")
    if not isinstance(runs, list):
        raise ValueError("workflow_runs 不是列表")
    return [run for run in runs if isinstance(run, dict)]


def _safe_json_path(raw: str) -> Path:
    """拒绝空路径、目录穿越；必须是已存在的普通文件。"""
    text = raw.strip()
    if not text or ".." in Path(text).parts:
        raise ValueError(f"非法 JSON 路径：{raw!r}")
    path = Path(text)
    if not path.is_file():
        raise ValueError(f"runs JSON 不是文件：{path}")
    return path


def decide_skip(
    *,
    event_name: str,
    workflow_file: str,
    window_hours: int,
    ref: str,
    runs_json: str,
    now: datetime | None = None,
    runs: list[dict[str, Any]] | None = None,
) -> bool:
    """非 schedule 永不跳过；schedule 则按 JSON 里的手动触发去重。"""
    if event_name != "schedule":
        return False
    require_allowed_workflow(workflow_file)
    listed = runs
    if listed is None:
        listed = load_runs(_safe_json_path(runs_json))
    return should_skip_runs(
        listed,
        now=now or datetime.now(timezone.utc),
        window_hours=window_hours,
        ref=ref or DEFAULT_REF,
    )


def _emit_skip(skip: bool) -> None:
    """写到 stdout，供 ``>> $GITHUB_OUTPUT`` 使用。"""
    print(f"skip={'true' if skip else 'false'}")


def main(argv: list[str] | None = None) -> int:
    """输出 skip=true/false。查询失败时 fail-open。"""
    args = parse_args(argv)
    event_name = os.getenv("GITHUB_EVENT_NAME", "").strip()
    try:
        skip = decide_skip(
            event_name=event_name,
            workflow_file=args.workflow_file,
            window_hours=args.window_hours,
            ref=args.ref or DEFAULT_REF,
            runs_json=args.runs_json,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"去重查询失败，不跳过迟到的 schedule：{error}", file=sys.stderr)
        _emit_skip(False)
        return 0
    _emit_skip(skip)
    if skip:
        print(
            "本机已在去重窗口内触发过 workflow_dispatch，跳过迟到的 GitHub schedule。",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
