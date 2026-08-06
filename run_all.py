"""JuJuBit UI 自动化完整回归入口。

直接运行本文件会执行 PC、H5 的全部 pytest + Playwright 用例，并把 HTML
报告、失败截图和失败录像归档到同一个带时间戳的目录。
"""

import argparse
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
RUN_ID = datetime.now().strftime("%Y%m%d-%H%M%S")
RUN_DIR = ROOT / "artifacts" / "runs" / RUN_ID
REPORT_NAME = f"jujubit-report-{RUN_ID}.html"
REPORT_PATH = RUN_DIR / REPORT_NAME


def _parse_args():
    """解析面向使用者的一键运行参数。"""
    parser = argparse.ArgumentParser(description="执行 JuJuBit 全部 UI 自动化用例")
    parser.add_argument(
        "--manual-verification",
        action="store_true",
        help="遇到 429/人机验证时显示浏览器，等待人工确认后继续。",
    )
    parser.add_argument(
        "--include-cart",
        action="store_true",
        help="同时执行会创建生成任务并修改购物车的端到端用例。",
    )
    return parser.parse_args()


def main() -> int:
    """拼装 pytest 命令，运行后清理仅用于中转的原始录像目录。"""
    args = _parse_args()
    # 每次运行使用独立目录，报告中的相对视频链接不会被下一次执行覆盖。
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        "pytest-playwright.ini",
        "--pw-platform",
        "all",
        "--pw-record-video",
        # 站点入口导航至少间隔 6 秒，减少连续访问触发站点 429 的概率。
        "--pw-request-interval",
        "6",
        # 429 时先等待后重试；若仍受限，会在报告中标为站点频控，而非业务用例失败。
        "--pw-429-retries",
        "2",
        # 链接扫描请求同样限速，避免 REQ-04 的批量校验触发站点频控。
        "--pw-link-request-interval",
        "0.8",
        "--pw-artifact-dir",
        str(RUN_DIR),
        "--pw-report-name",
        REPORT_NAME,
        "--html",
        str(REPORT_PATH),
        "--self-contained-html",
        "--junitxml",
        str(RUN_DIR / "results.xml"),
        "--tb=no",
    ]
    if args.manual_verification:
        # 人机验证必须由使用者在可见浏览器中完成，脚本只负责等待并继续执行。
        command.extend(["--headed", "--pw-manual-verification"])
    if not args.include_cart:
        # 购物车主流程会真实创建生成任务；默认回归不产生这类外部副作用。
        command.extend(["-m", "not cart_session"])
    result = subprocess.run(command, cwd=ROOT)
    # Playwright 必须先关闭上下文才能写完视频；保留已重命名的失败视频即可。
    raw_video_dir = RUN_DIR / "failure-videos" / "raw"
    if raw_video_dir.exists():
        shutil.rmtree(raw_video_dir)
    print(f"\n时间戳报告：{REPORT_PATH}")
    print(f"失败视频：{RUN_DIR / 'failure-videos'}")
    print("如出现人机验证，请改用：.venv/bin/python run_all.py --manual-verification")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
