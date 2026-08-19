#!/usr/bin/env python3
"""校验 Playwright Codegen 录制是否适合进入评审和版本库。

校验器只做静态检查：语法、元数据、明显不稳定定位器和可能的敏感输入。
它不会执行录制脚本，也不会访问站点。
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Sequence


REQUIRED_MANIFEST_KEYS = {
    "schema_version",
    "name",
    "platform",
    "url",
    "target",
    "flow_file",
}
UNSTABLE_LOCATOR_PATTERNS = (
    # 只匹配 XPath 参数或以 ``//`` 开头的选择器，避免把 https:// URL 误报为 XPath。
    (re.compile(r"xpath\s*=|['\"]//[A-Za-z]"), "发现 XPath 定位；优先改为 role/label/testid 或稳定业务属性。"),
    (re.compile(r"\.nth\s*\("), "发现 nth() 定位；请确认是否能用唯一语义或 data-testid 替代。"),
    (re.compile(r"\.first\s*\(|\.last\s*\("), "发现 first()/last() 定位；页面排序变化可能导致误选。"),
)
SLEEP_PATTERNS = (
    (re.compile(r"time\.sleep\s*\("), "发现 time.sleep；应改为等待可观察页面状态。"),
    (re.compile(r"wait_for_timeout\s*\("), "发现 wait_for_timeout；仅保留真实动画所需的最小等待。"),
)
SECRET_PATTERNS = (
    re.compile(r"(?i)(password|passwd|otp|verification[_ -]?code|authorization|bearer)\s*[=:,]\s*['\"][^'\"]+['\"]"),
    re.compile(r"(?i)page\.(?:get_by_label|locator|get_by_role)\([^\n]*password[^\n]*\)\.fill\([^\n]*['\"][^'\"]+['\"]"),
)


@dataclass
class ValidationResult:
    """静态校验结果；warnings 不会阻止普通模式通过。"""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _recording_files(path: Path) -> tuple[Path, Path | None]:
    """解析录制目录或 flow.py 路径。"""
    resolved = path.expanduser().resolve()
    if resolved.is_dir():
        return resolved / "flow.py", resolved / "recording.json"
    if resolved.suffix == ".py":
        return resolved, resolved.parent / "recording.json"
    raise ValueError(f"录制路径必须是目录或 .py 文件：{path}")


def _load_manifest(path: Path | None, result: ValidationResult) -> dict:
    if path is None or not path.is_file():
        result.warnings.append("未找到 recording.json；单独的 flow.py 可以验证，但无法追溯录制元数据。")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        result.errors.append(f"recording.json 无法解析：{error}")
        return {}
    if not isinstance(payload, dict):
        result.errors.append("recording.json 顶层必须是 JSON 对象。")
        return {}
    missing = REQUIRED_MANIFEST_KEYS - payload.keys()
    if missing:
        result.errors.append("recording.json 缺少字段：" + ", ".join(sorted(missing)))
    if payload.get("platform") not in {"pc", "h5"}:
        result.errors.append("recording.json 的 platform 必须为 pc 或 h5。")
    if not str(payload.get("url") or "").startswith(("http://", "https://")):
        result.errors.append("recording.json 的 url 必须是 http/https 地址。")
    if payload.get("status") not in {None, "completed", "dry-run"}:
        result.warnings.append(
            f"录制状态为 {payload.get('status')!r}，接受前请确认 Codegen 已正常结束。"
        )
    return payload


def validate_recording(path: str | Path) -> ValidationResult:
    """静态校验一个录制目录或录制脚本。"""
    result = ValidationResult()
    try:
        flow_file, manifest_file = _recording_files(Path(path))
    except ValueError as error:
        result.errors.append(str(error))
        return result
    manifest = _load_manifest(manifest_file, result)
    if not flow_file.is_file():
        result.errors.append(f"未找到录制脚本：{flow_file}")
        return result

    try:
        source = flow_file.read_text(encoding="utf-8")
    except OSError as error:
        result.errors.append(f"录制脚本无法读取：{error}")
        return result
    try:
        tree = ast.parse(source, filename=str(flow_file))
        compile(tree, str(flow_file), "exec")
    except SyntaxError as error:
        result.errors.append(f"录制脚本存在语法错误：第 {error.lineno} 行 {error.msg}")
        return result
    except (TypeError, ValueError) as error:
        result.errors.append(f"录制脚本无法编译：{error}")
        return result

    if manifest.get("target") == "python-pytest":
        functions = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        ]
        if not functions:
            result.warnings.append("目标为 python-pytest，但脚本没有 test_ 开头的测试函数。")

    expected_flow = str(manifest.get("flow_file") or "")
    if expected_flow and expected_flow != flow_file.name:
        result.errors.append(
            f"recording.json 的 flow_file={expected_flow!r} 与实际文件 {flow_file.name!r} 不一致。"
        )

    for pattern, message in UNSTABLE_LOCATOR_PATTERNS:
        if pattern.search(source):
            result.warnings.append(message)
    for pattern, message in SLEEP_PATTERNS:
        if pattern.search(source):
            result.warnings.append(message)
    for pattern in SECRET_PATTERNS:
        if pattern.search(source):
            result.errors.append("录制脚本疑似包含明文凭据或授权信息；请脱敏后再继续。")
            break
    if "page.goto(" not in source:
        result.warnings.append("录制脚本没有 page.goto；请确认它包含完整的入口导航。")
    return result


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="静态检查 Playwright Codegen 录制。")
    parser.add_argument("recording", help="录制目录或 flow.py 路径")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="把定位器/等待等 warning 也视为失败，适合提交前检查。",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    result = validate_recording(args.recording)
    for message in result.errors:
        print(f"ERROR: {message}", file=sys.stderr)
    for message in result.warnings:
        print(f"WARN: {message}")
    if result.errors:
        return 1
    if args.strict and result.warnings:
        return 1
    print("录制静态校验通过。请继续人工评审定位器，并将稳定动作回填到 Page Object。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
