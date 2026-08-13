"""购物车共享 BrowserContext 的离线生命周期测试。"""

from pathlib import Path
import unittest

from python_playwright.tests.conftest import (
    VIEWPORTS,
    _CartContextPool,
    _capture_cart_session_storage,
    _restore_cart_session_storage,
)


class _Config:
    def __init__(self, artifact_dir: Path, *, record_video: bool = False):
        self.artifact_dir = artifact_dir
        self.record_video = record_video
        self._jujubit_cart_session_storage = {}

    def getoption(self, name: str):
        return {
            "--pw-artifact-dir": str(self.artifact_dir),
            "--pw-record-video": self.record_video,
        }[name]


class _Context:
    def __init__(self, options):
        self.options = options
        self.closed = False

    def close(self):
        self.closed = True


class _BrokenContext(_Context):
    def close(self):
        self.closed = True
        raise RuntimeError("模拟 Context 已异常关闭")


class _Browser:
    def __init__(self):
        self.contexts = []

    def new_context(self, **options):
        context = _Context(options)
        self.contexts.append(context)
        return context


class _Page:
    def __init__(self, snapshot=None):
        self.snapshot = snapshot
        self.init_scripts = []

    def add_init_script(self, *, script):
        self.init_scripts.append(script)

    def evaluate(self, expression):
        if isinstance(self.snapshot, Exception):
            raise self.snapshot
        return self.snapshot


class CartContextPoolTests(unittest.TestCase):
    def test_same_platform_reuses_context_and_different_platform_is_isolated(self):
        browser = _Browser()
        storage_state = Path("artifacts/auth/storage-state.json")
        pool = _CartContextPool(
            browser,
            _Config(Path("artifacts/test-context-pool")),
            storage_state,
        )

        pc_first = pool.get("pc")
        pc_second = pool.get("pc")
        h5 = pool.get("h5")

        self.assertIs(pc_first, pc_second)
        self.assertIsNot(pc_first, h5)
        self.assertEqual(len(browser.contexts), 2)
        self.assertEqual(pc_first.options["viewport"], VIEWPORTS["pc"])
        self.assertEqual(pc_first.options["storage_state"], str(storage_state))
        self.assertEqual(h5.options["viewport"], VIEWPORTS["h5"])
        self.assertTrue(h5.options["is_mobile"])
        self.assertTrue(h5.options["has_touch"])

    def test_close_only_closes_contexts_that_were_created(self):
        browser = _Browser()
        pool = _CartContextPool(
            browser,
            _Config(Path("artifacts/test-context-pool")),
            Path("artifacts/auth/storage-state.json"),
        )
        pc = pool.get("pc")

        pool.close()

        self.assertTrue(pc.closed)
        self.assertEqual(len(browser.contexts), 1)

    def test_video_directory_is_only_configured_when_recording_is_enabled(self):
        browser = _Browser()
        artifact_dir = Path("artifacts/test-context-pool")
        pool = _CartContextPool(
            browser,
            _Config(artifact_dir, record_video=True),
            Path("artifacts/auth/storage-state.json"),
        )

        pc = pool.get("pc")

        self.assertEqual(
            pc.options["record_video_dir"],
            str(artifact_dir / "failure-videos" / "raw"),
        )

    def test_unknown_platform_is_rejected_before_creating_context(self):
        browser = _Browser()
        pool = _CartContextPool(
            browser,
            _Config(Path("artifacts/test-context-pool")),
            Path("artifacts/auth/storage-state.json"),
        )

        with self.assertRaisesRegex(ValueError, "不支持的购物车测试平台"):
            pool.get("tablet")

        self.assertEqual(browser.contexts, [])

    def test_close_continues_when_one_context_was_already_broken(self):
        browser = _Browser()
        pool = _CartContextPool(
            browser,
            _Config(Path("artifacts/test-context-pool")),
            Path("artifacts/auth/storage-state.json"),
        )
        broken = _BrokenContext({})
        healthy = _Context({})
        pool.contexts = {"pc": broken, "h5": healthy}

        pool.close()

        self.assertTrue(broken.closed)
        self.assertTrue(healthy.closed)

    def test_session_storage_is_captured_per_platform_and_restored(self):
        config = _Config(Path("artifacts/test-context-pool"))
        captured = _Page(
            {"origin": "https://jujubit.ai", "entries": {"gallery": "asset-1"}}
        )

        _capture_cart_session_storage(captured, config, "pc")
        restored = _Page()
        _restore_cart_session_storage(restored, config, "pc")

        self.assertEqual(
            config._jujubit_cart_session_storage,
            {"pc": {"https://jujubit.ai": {"gallery": "asset-1"}}},
        )
        self.assertEqual(len(restored.init_scripts), 1)
        self.assertIn("asset-1", restored.init_scripts[0])
        h5 = _Page()
        _restore_cart_session_storage(h5, config, "h5")
        self.assertEqual(h5.init_scripts, [])

    def test_invalid_or_unavailable_session_storage_is_ignored(self):
        config = _Config(Path("artifacts/test-context-pool"))

        _capture_cart_session_storage(
            _Page({"origin": "null", "entries": {"gallery": "asset-1"}}),
            config,
            "pc",
        )
        _capture_cart_session_storage(_Page(RuntimeError("页面已关闭")), config, "pc")

        self.assertEqual(config._jujubit_cart_session_storage, {})


if __name__ == "__main__":
    unittest.main()
