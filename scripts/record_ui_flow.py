#!/usr/bin/env python3
"""启动 Playwright Codegen，生成可评审的真实 UI 操作录制。

录制是探索和定位变更的输入，不是直接替代项目中的 pytest/Page Object。
默认输出到 ``recorded/inbox``，人工确认并完成脱敏后再移动到受版本控制的
``recorded/accepted``，最后把稳定动作回填到页面对象和现有测试中。
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Sequence
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "https://jujubit.ai/"
DEFAULT_TARGET = "python-pytest"
DEFAULT_TEST_ID_ATTRIBUTE = "data-testid"
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def normalize_slug(value: str) -> str:
    """校验目录名，避免把任意路径拼接进录制产物目录。"""
    slug = value.strip().lower()
    if not SLUG_PATTERN.fullmatch(slug):
        raise ValueError(
            "录制名称只能包含小写字母、数字、下划线和短横线，且必须以字母或数字开头。"
        )
    return slug


def recording_output_dir(
    name: str,
    platform: str,
    *,
    now: datetime | None = None,
    root: Path = ROOT,
) -> Path:
    """返回默认的、按时间隔离的录制收件目录。"""
    if platform not in {"pc", "h5"}:
        raise ValueError(f"不支持的录制端：{platform}")
    timestamp = (now or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")
    return root / "recorded" / "inbox" / f"{timestamp}-{normalize_slug(name)}-{platform}"


def _absolute_path(value: str | Path, *, base: Path = ROOT) -> Path:
    """把命令行路径解析为绝对路径；相对路径以仓库根目录为基准。"""
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def safe_recording_url(url: str) -> str:
    """去掉 query/fragment，避免把 URL 中的 token 写进录制元数据。"""
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))


def build_codegen_command(
    *,
    output_file: Path,
    url: str,
    platform: str,
    target: str = DEFAULT_TARGET,
    load_storage: Path | None = None,
    save_storage: Path | None = None,
    save_har: Path | None = None,
    test_id_attribute: str = DEFAULT_TEST_ID_ATTRIBUTE,
    channel: str = "",
    user_data_dir: Path | None = None,
    timeout: int | None = None,
    executable: Sequence[str] | None = None,
) -> list[str]:
    """构造 Codegen 命令，单独暴露便于离线测试和审查。"""
    if platform not in {"pc", "h5"}:
        raise ValueError(f"不支持的录制端：{platform}")
    if not url.strip():
        raise ValueError("录制 URL 不能为空")
    if timeout is not None and timeout <= 0:
        raise ValueError("录制超时时间必须大于 0")

    command = list(executable or (sys.executable, "-m", "playwright"))
    command.extend(
        [
            "codegen",
            "--target",
            target,
            "--output",
            str(output_file),
        ]
    )
    if test_id_attribute:
        command.extend(["--test-id-attribute", test_id_attribute])
    if platform == "h5":
        # iPhone 13 的 390x844 视口与当前仓库 H5 fixture 保持一致。
        command.extend(["--device", "iPhone 13"])
    else:
        command.extend(["--viewport-size", "1440,900"])
    if channel:
        command.extend(["--channel", channel])
    if load_storage is not None:
        command.extend(["--load-storage", str(load_storage)])
    if save_storage is not None:
        command.extend(["--save-storage", str(save_storage)])
    if save_har is not None:
        command.extend(["--save-har", str(save_har)])
    if user_data_dir is not None:
        command.extend(["--user-data-dir", str(user_data_dir)])
    if timeout is not None:
        command.extend(["--timeout", str(timeout)])
    command.append(url)
    return command


def _manifest_for(
    *,
    name: str,
    platform: str,
    url: str,
    target: str,
    flow_file: Path,
    command: Sequence[str],
    load_storage: Path | None,
    save_storage: Path | None,
    save_har: Path | None,
) -> dict:
    """生成不包含 Cookie/凭据内容的录制元数据。"""
    safe_url = safe_recording_url(url)
    safe_command = list(command)
    # Codegen 命令最后一个参数是入口 URL；manifest 只保留脱敏后的版本。
    if safe_command:
        safe_command[-1] = safe_url
    return {
        "schema_version": 1,
        "name": name,
        "platform": platform,
        "url": safe_url,
        "target": target,
        "flow_file": flow_file.name,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "recording",
        "load_storage_requested": load_storage is not None,
        "save_storage_requested": save_storage is not None,
        "save_har_requested": save_har is not None,
        # 只记录可审查的启动命令；状态文件内容永远不会写入 manifest。
        "command": safe_command,
    }


def _write_manifest(path: Path, manifest: dict) -> None:
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="用真实浏览器录制 JuJuBit UI 流程，并生成可评审的 Playwright 脚本。"
    )
    parser.add_argument("--name", required=True, help="录制名称，例如 homepage-header")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"开始录制的 URL（默认 {DEFAULT_URL}）")
    parser.add_argument("--platform", choices=("pc", "h5"), default="pc")
    parser.add_argument("--target", default=DEFAULT_TARGET, help="Playwright Codegen 输出语言/目标")
    parser.add_argument(
        "--output-dir",
        help="录制目录；省略时写入 recorded/inbox/<时间>-<名称>-<端>",
    )
    parser.add_argument(
        "--load-storage",
        help="可选的登录态 JSON，只传路径；不要把文件提交到仓库。",
    )
    parser.add_argument(
        "--save-storage",
        help="可选的登录态保存路径；建议放在 artifacts/auth/。",
    )
    parser.add_argument(
        "--save-har",
        help="可选 HAR 输出路径；HAR 可能包含敏感请求，默认不生成。",
    )
    parser.add_argument(
        "--user-data-dir",
        help="可选的浏览器用户目录；仅在明确需要复用本机浏览器配置时使用。",
    )
    parser.add_argument("--channel", default="", help="可选浏览器 channel，例如 chrome")
    parser.add_argument("--timeout", type=int, help="可选动作超时时间（毫秒）")
    parser.add_argument(
        "--test-id-attribute",
        default=DEFAULT_TEST_ID_ATTRIBUTE,
        help="Codegen 优先使用的测试属性（默认 data-testid）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="允许写入已有且非空的输出目录（会覆盖其中同名 flow.py/manifest 文件）。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要执行的命令，不启动浏览器。",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        name = normalize_slug(args.name)
        output_dir = (
            recording_output_dir(name, args.platform)
            if not args.output_dir
            else _absolute_path(args.output_dir)
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        flow_file = output_dir / "flow.py"
        manifest_file = output_dir / "recording.json"
        if not args.force:
            existing = [path for path in (flow_file, manifest_file) if path.exists()]
            if existing:
                raise ValueError(
                    "输出目录中已经存在录制文件："
                    + ", ".join(str(path) for path in existing)
                    + "；请换目录或使用 --force。"
                )

        load_storage = (
            _absolute_path(args.load_storage) if args.load_storage else None
        )
        save_storage = (
            _absolute_path(args.save_storage) if args.save_storage else None
        )
        save_har = _absolute_path(args.save_har) if args.save_har else None
        user_data_dir = (
            _absolute_path(args.user_data_dir) if args.user_data_dir else None
        )
        if load_storage is not None and not load_storage.is_file():
            raise ValueError(f"登录态文件不存在：{load_storage}")
        for destination in (save_storage, save_har):
            if destination is not None:
                destination.parent.mkdir(parents=True, exist_ok=True)

        command = build_codegen_command(
            output_file=flow_file,
            url=args.url,
            platform=args.platform,
            target=args.target,
            load_storage=load_storage,
            save_storage=save_storage,
            save_har=save_har,
            test_id_attribute=args.test_id_attribute,
            channel=args.channel,
            user_data_dir=user_data_dir,
            timeout=args.timeout,
        )
        manifest = _manifest_for(
            name=name,
            platform=args.platform,
            url=args.url,
            target=args.target,
            flow_file=flow_file,
            command=command,
            load_storage=load_storage,
            save_storage=save_storage,
            save_har=save_har,
        )
        _write_manifest(manifest_file, manifest)

        print(f"录制目录：{output_dir}")
        print("录制完成后关闭 Codegen 窗口；生成的 flow.py 只作为评审输入。")
        print(f"启动命令：{shlex.join(command)}")
        if args.dry_run:
            manifest["status"] = "dry-run"
            _write_manifest(manifest_file, manifest)
            return 0

        try:
            result = subprocess.run(command, cwd=ROOT)
            return_code = result.returncode
        except KeyboardInterrupt:
            return_code = 130
        manifest["status"] = "completed" if return_code == 0 else "failed"
        manifest["exit_code"] = return_code
        manifest["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        _write_manifest(manifest_file, manifest)
        if return_code == 0:
            print(
                "录制已完成。下一步：运行 validate_recording.py，脱敏并评审定位器，"
                "再将稳定动作回填到 HomePage/Page Object。"
            )
        else:
            print(f"Codegen 退出码为 {return_code}；请查看 {manifest_file}", file=sys.stderr)
        return return_code
    except (OSError, ValueError) as error:
        print(f"录制启动失败：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
