"""page fixture 的 429 熔断闸门：冷却后必须放行，而不是废掉整轮用例。

历史上一次瞬时 429 会让整轮剩余购物车用例全部 skip（出现过 17/30、7/21），
因为熔断状态只在会话开始时初始化一次，之后永不解除。这里锁定冷却半开行为。
"""

from __future__ import annotations

import time
import unittest

from python_playwright.tests.conftest import _active_rate_limit_reason


class _Config:
    def __init__(self, cooldown: float):
        self.cooldown = cooldown
        self._jujubit_cart_rate_limited = ""
        self._jujubit_site_rate_limited = ""
        self._jujubit_cart_rate_limited_at = None
        self._jujubit_site_rate_limited_at = None

    def getoption(self, name: str):
        if name == "--pw-429-cooldown":
            return self.cooldown
        raise AssertionError(f"未预期读取配置项：{name}")


REASON = "站点访问频控（HTTP 429）：jujubit.ai/cart.js 未完成。"


class RateLimitCooldownGateTests(unittest.TestCase):
    def test_no_circuit_means_case_runs_normally(self) -> None:
        self.assertEqual(_active_rate_limit_reason(_Config(120.0)), "")

    def test_reason_is_returned_while_still_cooling_down(self) -> None:
        config = _Config(120.0)
        config._jujubit_cart_rate_limited = REASON
        config._jujubit_cart_rate_limited_at = time.monotonic() - 30

        self.assertEqual(_active_rate_limit_reason(config), REASON)

    def test_circuit_clears_once_cooldown_has_elapsed(self) -> None:
        config = _Config(120.0)
        config._jujubit_cart_rate_limited = REASON
        config._jujubit_site_rate_limited = REASON
        config._jujubit_cart_rate_limited_at = time.monotonic() - 121

        self.assertEqual(_active_rate_limit_reason(config), "")
        # 闸门放行时必须同时清空两个熔断标记，否则下一条用例又会被挡住。
        self.assertEqual(config._jujubit_cart_rate_limited, "")
        self.assertEqual(config._jujubit_site_rate_limited, "")
        self.assertIsNone(config._jujubit_cart_rate_limited_at)

    def test_site_level_timestamp_is_used_when_cart_timestamp_missing(self) -> None:
        """首页熔断只写站点级标记；闸门必须能读到它的时刻。"""
        config = _Config(120.0)
        config._jujubit_site_rate_limited = REASON
        config._jujubit_site_rate_limited_at = time.monotonic() - 200

        self.assertEqual(_active_rate_limit_reason(config), "")

    def test_cooldown_zero_keeps_circuit_open_for_whole_session(self) -> None:
        config = _Config(0.0)
        config._jujubit_cart_rate_limited = REASON
        config._jujubit_cart_rate_limited_at = time.monotonic() - 10_000

        self.assertEqual(_active_rate_limit_reason(config), REASON)

    def test_missing_timestamp_falls_back_to_blocking(self) -> None:
        """旧状态没有时刻字段时保持保守：继续熔断而不是误放行。"""
        config = _Config(120.0)
        config._jujubit_cart_rate_limited = REASON

        self.assertEqual(_active_rate_limit_reason(config), REASON)


if __name__ == "__main__":
    unittest.main()
