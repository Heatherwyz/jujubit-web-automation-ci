#!/usr/bin/env python3
"""为本机安装或卸载北京时间 09:00 / 21:00 的 LaunchAgent。

准时触发必须跑在这台已经 ``gh auth login`` 过的 Mac 上：GitHub 自己的
``schedule`` 对本仓库长期迟到 4–5 小时。本脚本只写用户级 LaunchAgent，
不写系统目录，不把 token 写进 plist。

飞书自定义机器人 Webhook 只能收结果，不能反向触发；安装后仍由现有工作流
把测试卡片推到飞书群。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape


LABEL = "com.jujubit.dispatch-scheduled-workflows"
ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / "scripts" / "dispatch_scheduled_workflows.py"
PYTHON = Path("/usr/bin/python3")
GH_DIR = Path("/opt/homebrew/bin")
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = LAUNCH_AGENTS / f"{LABEL}.plist"
LOG_PATH = Path.home() / "Library" / "Logs" / f"{LABEL}.log"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """安装、卸载或只打印 plist。"""
    parser = argparse.ArgumentParser(description="安装本机 09:00/21:00 准时触发")
    parser.add_argument(
        "action",
        choices=("install", "uninstall", "print"),
        help="install 写入 LaunchAgent；uninstall 卸载；print 只打印 plist",
    )
    return parser.parse_args(argv)


def plist_text() -> str:
    """生成只含本仓库绝对路径的 LaunchAgent。"""
    python = str(PYTHON)
    script = str(DISPATCH)
    workdir = str(ROOT)
    log = str(LOG_PATH)
    path_value = f"{GH_DIR}:/usr/local/bin:/usr/bin:/bin"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{escape(LABEL)}</string>
    <key>WorkingDirectory</key>
    <string>{escape(workdir)}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{escape(python)}</string>
        <string>{escape(script)}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{escape(path_value)}</string>
        <key>TZ</key>
        <string>Asia/Shanghai</string>
    </dict>
    <key>StartCalendarInterval</key>
    <array>
        <dict>
            <key>Hour</key>
            <integer>9</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>21</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
    </array>
    <key>StandardOutPath</key>
    <string>{escape(log)}</string>
    <key>StandardErrorPath</key>
    <string>{escape(log)}</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""


def _run_launchctl(*args: str, ignore_failure: bool = False) -> None:
    completed = subprocess.run(
        ["launchctl", *args],
        shell=False,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0 or ignore_failure:
        return
    stderr = completed.stderr or ""
    if "No such process" in stderr or "Could not find specified service" in stderr:
        return
    message = stderr.strip() or (completed.stdout or "").strip() or "未知错误"
    raise RuntimeError(f"launchctl {' '.join(args)} 失败：{message}")


def install() -> None:
    """写入用户 LaunchAgent 并加载。"""
    if not DISPATCH.is_file():
        raise RuntimeError(f"找不到触发脚本：{DISPATCH}")
    if not PYTHON.is_file():
        raise RuntimeError(f"找不到 {PYTHON}，无法作为 LaunchAgent 解释器")
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist_text(), encoding="utf-8")
    uid = os.getuid()
    target = f"gui/{uid}/{LABEL}"
    _run_launchctl("bootout", f"gui/{uid}", str(PLIST_PATH), ignore_failure=True)
    _run_launchctl("bootstrap", f"gui/{uid}", str(PLIST_PATH))
    _run_launchctl("enable", target)
    print(f"已安装 {PLIST_PATH}")
    print("每天北京时间 09:00 和 21:00 会调用 gh workflow run 触发三个工作流。")
    print(f"日志：{LOG_PATH}")


def uninstall() -> None:
    """卸载用户 LaunchAgent。"""
    uid = os.getuid()
    if PLIST_PATH.is_file():
        _run_launchctl("bootout", f"gui/{uid}", str(PLIST_PATH), ignore_failure=True)
        PLIST_PATH.unlink()
        print(f"已删除 {PLIST_PATH}")
    else:
        print(f"未找到 {PLIST_PATH}，无需卸载。")


def main(argv: list[str] | None = None) -> int:
    """安装、卸载或打印 plist。"""
    args = parse_args(argv)
    try:
        if args.action == "print":
            sys.stdout.write(plist_text())
            return 0
        if args.action == "uninstall":
            uninstall()
            return 0
        install()
        return 0
    except (OSError, RuntimeError) as error:
        print(f"本机定时安装失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
