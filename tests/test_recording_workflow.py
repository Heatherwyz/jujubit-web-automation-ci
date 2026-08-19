"""真实录制工作流工具的离线测试。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime

from scripts.record_ui_flow import (
    build_codegen_command,
    recording_output_dir,
    safe_recording_url,
)
from scripts.validate_recording import validate_recording


class RecordingWorkflowTests(unittest.TestCase):
    """保证录制命令和静态校验规则不会无意漂移。"""

    def test_codegen_command_uses_current_pc_viewport_and_testid(self) -> None:
        command = build_codegen_command(
            output_file=Path("/tmp/flow.py"),
            url="https://jujubit.ai/",
            platform="pc",
        )

        self.assertIn("--target", command)
        self.assertIn("python-pytest", command)
        self.assertIn("--viewport-size", command)
        self.assertIn("1440,900", command)
        self.assertIn("--test-id-attribute", command)
        self.assertIn("data-testid", command)
        self.assertNotIn("--device", command)

    def test_codegen_command_uses_h5_device_and_explicit_storage_paths(self) -> None:
        command = build_codegen_command(
            output_file=Path("/tmp/flow.py"),
            url="https://jujubit.ai/",
            platform="h5",
            load_storage=Path("/tmp/storage.json"),
            save_har=Path("/tmp/flow.har"),
        )

        self.assertIn("--device", command)
        self.assertIn("iPhone 13", command)
        self.assertIn("--load-storage", command)
        self.assertIn("/tmp/storage.json", command)
        self.assertIn("--save-har", command)
        self.assertNotIn("--viewport-size", command)

    def test_default_recording_directory_is_timestamped_and_scoped(self) -> None:
        output = recording_output_dir(
            "Homepage-Change",
            "pc",
            now=datetime(2026, 8, 19, 12, 34, 56),
            root=Path("/repo"),
        )

        self.assertEqual(
            output,
            Path("/repo/recorded/inbox/20260819-123456-homepage-change-pc"),
        )

    def test_manifest_url_helper_removes_query_and_fragment(self) -> None:
        self.assertEqual(
            safe_recording_url("https://jujubit.ai/pages/home?token=secret#hero"),
            "https://jujubit.ai/pages/home",
        )

    def test_validator_accepts_sanitized_pytest_recording(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "flow.py").write_text(
                "from playwright.sync_api import expect\n\n"
                "def test_recorded(page):\n"
                "    page.goto('https://jujubit.ai/')\n"
                "    expect(page.get_by_role('main')).to_be_visible()\n",
                encoding="utf-8",
            )
            (root / "recording.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "homepage",
                        "platform": "pc",
                        "url": "https://jujubit.ai/",
                        "target": "python-pytest",
                        "flow_file": "flow.py",
                    }
                ),
                encoding="utf-8",
            )

            result = validate_recording(root)

        self.assertTrue(result.ok)
        self.assertEqual(result.errors, [])

    def test_validator_rejects_literal_password_and_bad_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "flow.py").write_text(
                "def test_recorded(page):\n"
                "    page.goto('https://jujubit.ai/')\n"
                "    page.get_by_label('Password').fill('secret-value')\n"
                "    if True\n",
                encoding="utf-8",
            )

            result = validate_recording(root)

        self.assertFalse(result.ok)
        self.assertTrue(any("语法错误" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
