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
        "--headed",
        action="store_true",
        help="使用可见浏览器执行，适合本地调试和现场演示。",
    )
    parser.add_argument(
        "--include-cart",
        action="store_true",
        help="同时执行会创建生成任务并修改购物车的端到端用例。",
    )
    parser.add_argument(
        "--cart-smoke",
        action="store_true",
        help="执行首页及 1 条单上下文购物车主链路；完整购物车回归请用 --include-cart。",
    )
    parser.add_argument(
        "--cart-smoke-only",
        action="store_true",
        help="只执行 1 条单上下文购物车主链路；供低频购物车 CI 使用，不执行首页。",
    )
    parser.add_argument(
        "--cart-only",
        action="store_true",
        help="只执行购物车全部用例，不执行首页用例。",
    )
    parser.add_argument(
        "--cart-request-interval",
        type=float,
        default=6.0,
        help="购物车关键请求之间的最小间隔（秒），默认 6 秒以降低 GitHub Runner 触发 429 的概率。",
    )
    parser.add_argument(
        "--platform",
        choices=("all", "pc", "h5"),
        default="all",
        help="执行端：all、pc 或 h5；默认同时执行 PC/H5。",
    )
    return parser.parse_args()


def main() -> int:
    """拼装 pytest 命令，运行后清理仅用于中转的原始录像目录。"""
    args = _parse_args()
    selected_cart_modes = (
        args.include_cart,
        args.cart_smoke,
        args.cart_smoke_only,
        args.cart_only,
    )
    if sum(bool(value) for value in selected_cart_modes) > 1:
        raise SystemExit(
            "--include-cart、--cart-smoke、--cart-smoke-only、--cart-only 只能选择一个。"
        )
    if args.cart_request_interval < 0:
        raise SystemExit("--cart-request-interval 不能小于 0。")
    # 每次运行使用独立目录，报告中的相对视频链接不会被下一次执行覆盖。
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        "pytest-playwright.ini",
        "--pw-platform",
        args.platform,
        "--pw-record-video",
        # 首页与站内链接探测共用 6 秒节流，避免 GitHub Runner 的突发访问触发 429。
        "--pw-request-interval",
        "6",
        # 429 时先等待后重试；若仍受限，会触发熔断并在报告中标为站点频控。
        "--pw-429-retries",
        "2",
        # 该值与首页导航保持一致；实际由共享节流器按二者较大值执行。
        "--pw-link-request-interval",
        "6",
        # 购物车 API 和关键导航与首页共享节流时钟，避免同一主机出现交错突发请求。
        "--pw-cart-request-interval",
        str(args.cart_request_interval),
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
    if args.headed or args.manual_verification:
        command.append("--headed")
    if args.manual_verification:
        # 人机验证必须由使用者在可见浏览器中完成，脚本只负责等待并继续执行。
        command.append("--pw-manual-verification")
    if args.cart_smoke:
        # 综合 Smoke 只跑 1 条单上下文主链路，避免多个登录上下文连续撞 WAF。
        command.extend(["-m", "not cart_session or cart_smoke"])
    elif args.cart_smoke_only:
        # 独立购物车工作流不重复跑首页，只验证低频代表性购物车路径。
        command.extend(["-m", "cart_session and cart_smoke"])
    elif args.cart_only:
        command.extend(["-m", "cart_session and not cart_smoke"])
    elif args.include_cart:
        # 完整回归保留原有 15 条逻辑用例；独立 CI Smoke 不重复计入 30 条记录。
        command.extend(["-m", "not cart_smoke"])
    elif not args.include_cart:
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
