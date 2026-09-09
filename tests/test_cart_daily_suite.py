"""购物车每日分层套件的离线收集测试。

这些测试只调用 pytest 的 ``--collect-only``，不会启动浏览器、读取登录态或访问站点。
它们防止有人把每日 H5 筛选重新写成脆弱的 ``-k`` 字符串后，悄悄从 21 条漂移回 30 条。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _collect_cart_suite(*, suite: str, platform: str = "all") -> list[str]:
    """收集指定购物车套件的 nodeid，不执行真实 UI 用例。"""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            "pytest-playwright.ini",
            "--collect-only",
            "--pw-platform",
            platform,
            "--pw-cart-suite",
            suite,
            "-m",
            "cart_session and not cart_smoke"
            if suite != "smoke"
            else "cart_session and cart_smoke",
            "-q",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise AssertionError(
            "pytest 收集失败：\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return [
        line.strip()
        for line in completed.stdout.splitlines()
        if "::test_" in line and line.strip().endswith("]"
        )
    ]


def _platform_counts(nodeids: list[str]) -> Counter[str]:
    """按 pytest 参数化后的平台后缀统计收集记录。"""
    return Counter(
        "h5" if nodeid.endswith("[h5]") else "pc"
        for nodeid in nodeids
    )


class CartDailySuiteCollectionTests(unittest.TestCase):
    """验证 daily/full/smoke 实际收集条数和平台组成。"""

    def test_daily_all_collects_pc_15_and_h5_key_6(self) -> None:
        nodeids = _collect_cart_suite(suite="daily")

        self.assertEqual(len(nodeids), 21)
        self.assertEqual(_platform_counts(nodeids), {"pc": 15, "h5": 6})

    def test_daily_h5_collects_exactly_six_key_cases(self) -> None:
        nodeids = _collect_cart_suite(suite="daily", platform="h5")

        self.assertEqual(len(nodeids), 6)
        self.assertEqual(
            {
                nodeid.rsplit("::", 1)[-1].removesuffix("[h5]")
                for nodeid in nodeids
            },
            {
                "test_cart_tc01_header_create_opens_creator",
                "test_cart_tc02_upload_result_has_2d_and_3d",
                "test_cart_tc03_gallery_add_opens_drawer",
                "test_cart_tc06_full_cart_checkout_opens_checkout",
                "test_cart_tc10_quantity_buttons_update_totals",
                "test_cart_tc15_failures_do_not_create_false_cart_state",
            },
        )

    def test_full_collects_all_thirty_pc_and_h5_records(self) -> None:
        nodeids = _collect_cart_suite(suite="full")

        self.assertEqual(len(nodeids), 30)
        self.assertEqual(_platform_counts(nodeids), {"pc": 15, "h5": 15})

    def test_smoke_remains_a_single_pc_main_path(self) -> None:
        nodeids = _collect_cart_suite(suite="smoke", platform="pc")

        self.assertEqual(
            nodeids,
            [
                "python_playwright/tests/test_cart.py::"
                "test_ci_smoke_generate_add_and_checkout[pc]"
            ],
        )


if __name__ == "__main__":
    unittest.main()
