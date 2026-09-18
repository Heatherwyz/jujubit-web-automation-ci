#!/usr/bin/env python3
"""在北京时间 09:00 / 21:00 用 GitHub CLI 准时触发三个工作流。

GitHub 自己的 ``schedule`` 对本仓库长期迟到 4–5 小时，所以准时触发改由本机
crontab / LaunchAgent 调用本脚本。``subprocess.run`` 只接收字面量参数列表，
``shell=False``，不把用户输入拼进命令。

飞书自定义机器人 Webhook 只能接收结果卡片，不能反向触发 GitHub；所以本脚本
不读写飞书。跑完后现有工作流仍会把结果推到飞书群。

购物车定时一律 ``daily``；完整 ``full`` 不走这条入口。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


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


def cart_suite_for(_now: datetime, _shift: str) -> str:
    """定时入口固定每日分层；完整回归不从这里触发。"""
    return "daily"


def _check(completed: subprocess.CompletedProcess[bytes], label: str) -> None:
    if completed.returncode != 0:
        raise RuntimeError(f"触发失败（退出码 {completed.returncode}）：{label}")


def dispatch_offline(*, dry_run: bool) -> None:
    """触发离线检查。"""
    print("gh workflow run offline-checks.yml --ref main")
    if dry_run:
        return
    _check(
        subprocess.run(
            [
                "gh",
                "workflow",
                "run",
                "offline-checks.yml",
                "--ref",
                "main",
            ],
            shell=False,
            check=False,
        ),
        "gh workflow run offline-checks.yml --ref main",
    )


def dispatch_home(*, dry_run: bool) -> None:
    """触发首页 UI 回归。"""
    print("gh workflow run daily-ui-tests.yml --ref main")
    if dry_run:
        return
    _check(
        subprocess.run(
            [
                "gh",
                "workflow",
                "run",
                "daily-ui-tests.yml",
                "--ref",
                "main",
            ],
            shell=False,
            check=False,
        ),
        "gh workflow run daily-ui-tests.yml --ref main",
    )


def dispatch_cart_daily(*, dry_run: bool) -> None:
    """触发购物车每日分层。"""
    print("gh workflow run cart-ui-tests.yml --ref main -f suite=daily")
    if dry_run:
        return
    _check(
        subprocess.run(
            [
                "gh",
                "workflow",
                "run",
                "cart-ui-tests.yml",
                "--ref",
                "main",
                "-f",
                "suite=daily",
            ],
            shell=False,
            check=False,
        ),
        "gh workflow run cart-ui-tests.yml --ref main -f suite=daily",
    )


def main(argv: list[str] | None = None) -> int:
    """按班次触发三个工作流；失败时非零退出，便于 crontab 发现。"""
    args = parse_args(argv)
    try:
        now = parse_now(args.now)
        shift = resolve_shift(now, args.shift)
        suite = cart_suite_for(now, shift)
        print(
            f"班次={shift} 北京时间={now.strftime('%Y-%m-%d %H:%M %Z')} "
            f"购物车套件={suite} ref=main"
        )
        dispatch_offline(dry_run=args.dry_run)
        dispatch_home(dry_run=args.dry_run)
        dispatch_cart_daily(dry_run=args.dry_run)
    except (ValueError, RuntimeError, OSError) as error:
        print(f"准时触发失败：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
