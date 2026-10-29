#!/usr/bin/env python
"""Trace path lifecycle tests for PlaywrightExecutor."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

from executor import PlaywrightExecutor


class ExecutorTracePathTest(unittest.IsolatedAsyncioTestCase):
    async def test_trace_path_survives_trace_session_close(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = PlaywrightExecutor(
                persistent=False,
                trace_enabled=True,
                trace_dir=tmpdir,
            )

            tracing = AsyncMock()
            tracing.stop = AsyncMock()
            context = AsyncMock()
            context.pages = []
            context.tracing = tracing
            context.close = AsyncMock()
            playwright = AsyncMock()
            playwright.stop = AsyncMock()
            page = MagicMock()

            async def fake_init_browser():
                executor._context = context
                executor._browser = None
                executor._playwright = playwright
                executor._page = page

            with patch.object(executor, "init_browser", new=fake_init_browser):
                async with executor.browser_session_with_trace("case_1") as active_page:
                    self.assertIs(active_page, page)

            trace_path = executor.get_current_trace_path()

            tracing.stop.assert_awaited_once()
            self.assertIsNotNone(trace_path)
            self.assertTrue(trace_path.startswith(f"{tmpdir}/case_1_"))
            self.assertTrue(trace_path.endswith(".zip"))

    async def test_trace_session_clears_stale_path_before_browser_init(self):
        executor = PlaywrightExecutor(persistent=False, trace_enabled=True)
        executor._current_trace_path = "/tmp/old-trace.zip"

        async def failing_init_browser():
            raise RuntimeError("browser failed")

        with patch.object(executor, "init_browser", new=failing_init_browser):
            with self.assertRaisesRegex(RuntimeError, "browser failed"):
                async with executor.browser_session_with_trace("case_2"):
                    pass

        self.assertIsNone(executor.get_current_trace_path())

    def _make_context(self):
        context = AsyncMock()
        context.pages = []
        context.close = AsyncMock()
        context.tracing = AsyncMock()
        return context

    async def test_trace_restarts_on_context_rebuild_and_saves(self):
        """登录态切换重建 context 后，Trace 必须在新 context 上重启并能正常落盘。

        回归：旧实现只在 init_browser 的 context 上 start，ensure_auth_context
        重建 context 后再 stop 会抛 "Must start tracing before stopping"。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = PlaywrightExecutor(persistent=False, trace_enabled=True, trace_dir=tmpdir)
            old_context = self._make_context()
            new_context = self._make_context()
            page = MagicMock()
            playwright = AsyncMock()

            async def fake_init_browser():
                executor._context = old_context
                executor._browser = None
                executor._playwright = playwright
                executor._page = page

            async def fake_rebuild():
                # 模拟 ensure_auth_context 内的关闭旧 context + 建新 context
                await old_context.close()
                executor._context = new_context
                executor._page = MagicMock()

            with patch.object(executor, "init_browser", new=fake_init_browser):
                async with executor.browser_session_with_trace("case_auth"):
                    old_context.tracing.start.assert_awaited_once()
                    with patch.object(executor, "_init_browser_context", new=fake_rebuild):
                        rebuilt = await executor.ensure_auth_context({"storage_state": None})
                    self.assertTrue(rebuilt)
                    new_context.tracing.start.assert_awaited_once()

            new_context.tracing.stop.assert_awaited_once()
            old_context.tracing.stop.assert_not_awaited()
            trace_path = executor.get_current_trace_path()
            self.assertIsNotNone(trace_path)
            self.assertTrue(trace_path.startswith(f"{tmpdir}/case_auth_"))

    async def test_stop_tracing_skips_when_context_replaced(self):
        """context 被替换（未重启 Trace）时，stop 应安全跳过而不是抛异常。"""
        executor = PlaywrightExecutor(persistent=False, trace_enabled=True)
        old_context = self._make_context()
        executor._tracing_context = old_context
        executor._tracing_active = True
        executor._context = self._make_context()

        saved = await executor._stop_tracing("/tmp/should-not-be-created.zip")

        self.assertIsNone(saved)
        old_context.tracing.stop.assert_not_awaited()
        self.assertFalse(executor._tracing_active)

    async def test_stop_tracing_skips_when_never_started(self):
        executor = PlaywrightExecutor(persistent=False, trace_enabled=True)
        context = self._make_context()
        executor._context = context

        saved = await executor._stop_tracing("/tmp/never-started.zip")

        self.assertIsNone(saved)
        context.tracing.stop.assert_not_awaited()

    async def test_stop_now_flushes_trace_before_closing(self):
        """手动中断（stop_now）应在关闭 context 前先把 Trace 落盘。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = PlaywrightExecutor(persistent=False, trace_enabled=True, trace_dir=tmpdir)
            context = self._make_context()
            executor._context = context
            executor._browser = None
            executor._playwright = AsyncMock()
            executor._page = MagicMock()
            executor._tracing_context = context
            executor._tracing_active = True
            executor._trace_name = "case_stop"

            await executor.stop_now()

            context.tracing.stop.assert_awaited_once()
            trace_path = executor.get_current_trace_path()
            self.assertIsNotNone(trace_path)
            self.assertTrue(trace_path.startswith(f"{tmpdir}/case_stop_"))

    def test_page_error_summary_dedupes_repeated_messages(self):
        executor = PlaywrightExecutor(persistent=False)
        executor._page_errors = ["BO", "BO", "BO", "sj_be is not defined"]

        note = executor._page_error_summary()

        self.assertIn("捕获 4 个页面 JS 错误", note)
        self.assertIn("BO×3", note)
        self.assertIn("sj_be is not defined", note)

    def test_page_error_summary_empty(self):
        executor = PlaywrightExecutor(persistent=False)
        self.assertEqual(executor._page_error_summary(), "")


if __name__ == "__main__":
    unittest.main()
