#!/usr/bin/env python3
"""在北京时间 09:00 / 21:00 用 GitHub CLI 准时触发每日全量回归。

为什么不用 GitHub 自己的 ``schedule``：对本仓库长期迟到 4–5 小时；而新建的
仓库还有一条硬限制——最近 60 天内没有 commit 活动时，定时任务根本不触发。
所以准时入口放在本机 crontab / LaunchAgent 调用本脚本。

``subprocess.run`` 只接收字面量参数列表，``shell=False``，不把用户输入拼进
命令。目标仓库显式传给 ``gh --repo``，不依赖当前工作目录的 remote——迁库后
本机 remote 改过，靠目录推断会打到错误的仓库。

飞书自定义机器人 Webhook 只能接收结果卡片，不能反向触发 GitHub；所以本脚本
不读写飞书。跑完后工作流自己会把结果推到飞书群。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")

# 每日全量回归：一个工作流按 Step 串行跑离线 → 首页 → 会员 → 购物车。
# 不再分别触发三个工作流：同仓库连续 dispatch 会撞 GITHUB_TOKEN 速率限制
# （历史上连续 HTTP 500）。
WORKFLOW_FILE = "daily-regression.yml"
DEFAULT_REPO = "Heatherwyz/jujubit-web-automation-ci"
# owner/repo 的合法字符集，防止环境变量把任意字符串带进命令参数。
# 首字符必须是字母或数字：以 - 开头的值会被 gh 当成命令行选项解析
# （例如 "--flag/x" 会变成一个 flag 而不是仓库名）。
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")


def resolve_repo(raw: str = "") -> str:
    """确定目标仓库：命令行 > 环境变量 > 默认值，并校验格式。"""
    candidate = (raw or os.environ.get("JUJUBIT_DISPATCH_REPO", "") or DEFAULT_REPO).strip()
    if not REPO_RE.match(candidate):
        raise ValueError(f"仓库名格式非法（应为 owner/repo）：{candidate!r}")
    return candidate


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析班次与是否只打印命令。始终触发 origin/main 上的三个工作流。"""
    parser = argparse.ArgumentParser(description="准时触发 JuJuBit 三个 GitHub 工作流")
    parser.add_argument(
        "--shift",
        choices=("auto", "morning", "evening"),
        default="auto",
        help="auto 按北京时间小时判断：12 点前早班，之后晚班",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将执行的 gh 命令，不真正触发",
    )
    parser.add_argument(
        "--now",
        default="",
        help="测试用：覆盖当前时间，格式 YYYY-MM-DDTHH:MM，按北京时间解释",
    )
    parser.add_argument(
        "--repo",
        default="",
        help=(
            "目标仓库 owner/repo；留空时取环境变量 JUJUBIT_DISPATCH_REPO，"
            f"再回落到 {DEFAULT_REPO}"
        ),
    )
    return parser.parse_args(argv)


def parse_now(raw: str, *, fallback: datetime | None = None) -> datetime:
    """得到带上海时区的当前时间。"""
    if raw:
        naive = datetime.strptime(raw, "%Y-%m-%dT%H:%M")
        return naive.replace(tzinfo=SHANGHAI)
    current = fallback or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        return current.replace(tzinfo=SHANGHAI)
    return current.astimezone(SHANGHAI)


def resolve_shift(now: datetime, requested: str) -> str:
    """12:00 前算早班，否则晚班。"""
    if requested in {"morning", "evening"}:
        return requested
    return "morning" if now.hour < 12 else "evening"


def _check(completed: subprocess.CompletedProcess[bytes], label: str) -> None:
    if completed.returncode != 0:
        raise RuntimeError(f"触发失败（退出码 {completed.returncode}）：{label}")


def dispatch_daily_regression(*, repo: str, dry_run: bool) -> None:
    """触发每日全量回归（离线 → 首页 → 会员 → 购物车，同 Job 串行）。"""
    label = f"gh workflow run {WORKFLOW_FILE} --repo {repo} --ref main"
    print(label)
    if dry_run:
        return
    _check(
        subprocess.run(
            [
                "gh",
                "workflow",
                "run",
                WORKFLOW_FILE,
                "--repo",
                repo,
                "--ref",
                "main",
            ],
            shell=False,
            check=False,
        ),
        label,
    )


def main(argv: list[str] | None = None) -> int:
    """按班次触发每日全量回归；失败时非零退出，便于 crontab 发现。"""
    args = parse_args(argv)
    try:
        repo = resolve_repo(args.repo)
        now = parse_now(args.now)
        shift = resolve_shift(now, args.shift)
        print(
            f"班次={shift} 北京时间={now.strftime('%Y-%m-%d %H:%M %Z')} "
            f"仓库={repo} ref=main"
        )
        dispatch_daily_regression(repo=repo, dry_run=args.dry_run)
    except (ValueError, RuntimeError, OSError) as error:
        print(f"准时触发失败：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
