"""Tests for writable Cursor handoff path resolution (prod bind-mount safe)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import contextlib


class TestWritableHandoffDir:
    def test_save_and_bridge_path_match(self, tmp_path):
        """save_cursor_handoff and _cursor_handoff_path must use the same directory."""
        d = tmp_path / "h"
        d.mkdir()
        with patch("app.services._paths.get_writable_cursor_handoffs_dir", return_value=d):
            from app.services.cursor_handoff import save_cursor_handoff
            from app.services.cursor_execution_bridge import _cursor_handoff_path

            out = save_cursor_handoff("task-a", "## prompt", title="t")
            assert out is not None
            assert out == d / "cursor-handoff-task-a.md"
            assert _cursor_handoff_path("task-a") == out

    def test_save_surfaces_permission_error_in_logs(self, tmp_path, caplog):
        """When write fails, warning includes exception type (e.g. PermissionError)."""
        import logging

        caplog.set_level(logging.WARNING)
        d = tmp_path / "ro"
        d.mkdir()

        def _boom(*a, **kw):
            raise PermissionError(13, "denied")

        with patch("app.services._paths.get_writable_cursor_handoffs_dir", return_value=d):
            with patch.object(Path, "write_text", side_effect=_boom):
                from app.services.cursor_handoff import save_cursor_handoff

                assert save_cursor_handoff("x", "body") is None
        assert "save_cursor_handoff failed" in caplog.text
        assert "PermissionError" in caplog.text

    def test_get_writable_dir_subdir_delegates_cursor_handoffs(self, tmp_path):
        d = tmp_path / "ch"
        d.mkdir()
        with patch("app.services._paths.get_writable_cursor_handoffs_dir", return_value=d):
            from app.services._paths import get_writable_dir_for_subdir

            assert get_writable_dir_for_subdir("docs/agents/cursor-handoffs") == d

    def test_phase2_returns_duplicate_when_lock_not_acquired(self):
        @contextlib.contextmanager
        def _no_lock(_task_id):
            yield False

        with patch.dict(
            "os.environ",
            {"CURSOR_BRIDGE_ENABLED": "true", "CURSOR_BRIDGE_REQUIRE_APPROVAL": "false"},
            clear=False,
        ):
            with patch(
                "app.services.cursor_execution_bridge._cursor_bridge_phase2_lock",
                _no_lock,
            ):
                from app.services.cursor_execution_bridge import run_bridge_phase2

                r = run_bridge_phase2("same-task", execution_context="telegram")
                assert r.get("duplicate_skipped") is True
                assert r.get("ok") is False
