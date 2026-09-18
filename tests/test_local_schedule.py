"""本机准时触发与迟到 schedule 去重的离线单测。"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.dispatch_scheduled_workflows import (
    cart_suite_for,
    main as dispatch_main,
    parse_now,
    resolve_shift,
)
from scripts.install_local_schedule import LABEL, plist_text
from scripts.should_skip_late_schedule import (
    decide_skip,
    load_runs,
    require_allowed_workflow,
    should_skip_runs,
)


# 模拟迟到的 GitHub schedule 实际触发时刻：北京时间 13:30（UTC 05:30）。
# 本机 09:00 的 workflow_dispatch 在 UTC 01:00，间隔约 4.5 小时，落在 11 小时窗口内。
NOW = datetime(2026, 9, 18, 5, 30, tzinfo=timezone.utc)


def _run(
    *,
    created_at: str,
    event: str = "workflow_dispatch",
    head_branch: str = "main",
    status: str = "completed",
    conclusion: str = "success",
) -> dict:
    return {
        "created_at": created_at,
        "event": event,
        "head_branch": head_branch,
        "status": status,
        "conclusion": conclusion,
    }


class ShiftAndSuiteTests(unittest.TestCase):
    def test_auto_shift_splits_at_noon_shanghai(self) -> None:
        morning = parse_now("2026-09-18T09:00")
        evening = parse_now("2026-09-18T21:00")
        self.assertEqual(resolve_shift(morning, "auto"), "morning")
        self.assertEqual(resolve_shift(evening, "auto"), "evening")

    def test_every_shift_uses_daily_cart_suite(self) -> None:
        sunday_morning = parse_now("2026-09-20T09:00")
        sunday_evening = parse_now("2026-09-20T21:00")
        friday_morning = parse_now("2026-09-18T09:00")
        self.assertEqual(sunday_morning.weekday(), 6)
        self.assertEqual(cart_suite_for(sunday_morning, "morning"), "daily")
        self.assertEqual(cart_suite_for(sunday_evening, "evening"), "daily")
        self.assertEqual(cart_suite_for(friday_morning, "morning"), "daily")


class DispatchDryRunTests(unittest.TestCase):
    def test_weekday_morning_dry_run_prints_daily_cart(self) -> None:
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            code = dispatch_main(
                ["--dry-run", "--now", "2026-09-18T09:00"]
            )
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("购物车套件=daily", text)
        self.assertIn("gh workflow run offline-checks.yml --ref main", text)
        self.assertIn("gh workflow run daily-ui-tests.yml --ref main", text)
        self.assertIn(
            "gh workflow run cart-ui-tests.yml --ref main -f suite=daily",
            text,
        )
        self.assertNotIn("suite=full", text)

    def test_sunday_morning_dry_run_also_prints_daily_cart(self) -> None:
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            code = dispatch_main(
                ["--dry-run", "--now", "2026-09-20T09:00"]
            )
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("购物车套件=daily", text)
        self.assertIn(
            "gh workflow run cart-ui-tests.yml --ref main -f suite=daily",
            text,
        )
        self.assertNotIn("suite=full", text)


class LaunchAgentPlistTests(unittest.TestCase):
    def test_plist_fires_at_nine_and_twenty_one(self) -> None:
        text = plist_text()
        self.assertIn(LABEL, text)
        self.assertIn("dispatch_scheduled_workflows.py", text)
        self.assertIn("<integer>9</integer>", text)
        self.assertIn("<integer>21</integer>", text)
        self.assertIn("Asia/Shanghai", text)
        self.assertNotIn("github_token", text.lower())
        self.assertNotIn("gho_", text)


class SkipLateScheduleTests(unittest.TestCase):
    def test_rejects_unknown_workflow_file(self) -> None:
        with self.assertRaises(ValueError):
            require_allowed_workflow("../evil.yml")

    def test_non_schedule_never_skips(self) -> None:
        skip = decide_skip(
            event_name="workflow_dispatch",
            workflow_file="daily-ui-tests.yml",
            window_hours=11,
            ref="main",
            runs_json="",
            now=NOW,
            runs=[_run(created_at="2026-09-18T01:00:00Z")],
        )
        self.assertFalse(skip)

    def test_recent_dispatch_on_main_skips_late_schedule(self) -> None:
        skip = should_skip_runs(
            [_run(created_at="2026-09-18T01:05:00Z")],
            now=NOW,
            window_hours=11,
            ref="main",
        )
        self.assertTrue(skip)

    def test_old_dispatch_does_not_skip(self) -> None:
        skip = should_skip_runs(
            [_run(created_at="2026-09-17T01:00:00Z")],
            now=NOW,
            window_hours=11,
            ref="main",
        )
        self.assertFalse(skip)

    def test_other_branch_or_cancelled_does_not_skip(self) -> None:
        other_branch = should_skip_runs(
            [_run(created_at="2026-09-18T01:05:00Z", head_branch="docs")],
            now=NOW,
            window_hours=11,
            ref="main",
        )
        cancelled = should_skip_runs(
            [
                _run(
                    created_at="2026-09-18T01:05:00Z",
                    status="completed",
                    conclusion="cancelled",
                )
            ],
            now=NOW,
            window_hours=11,
            ref="main",
        )
        self.assertFalse(other_branch)
        self.assertFalse(cancelled)

    def test_schedule_event_in_json_does_not_count_as_local_dispatch(self) -> None:
        skip = should_skip_runs(
            [_run(created_at="2026-09-18T01:05:00Z", event="schedule")],
            now=NOW,
            window_hours=11,
            ref="main",
        )
        self.assertFalse(skip)

    def test_load_runs_accepts_wrapped_and_bare_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wrapped = Path(tmp) / "wrapped.json"
            bare = Path(tmp) / "bare.json"
            payload = [_run(created_at="2026-09-18T01:05:00Z")]
            wrapped.write_text(
                json.dumps({"workflow_runs": payload}), encoding="utf-8"
            )
            bare.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(len(load_runs(wrapped)), 1)
            self.assertEqual(len(load_runs(bare)), 1)


if __name__ == "__main__":
    unittest.main()
