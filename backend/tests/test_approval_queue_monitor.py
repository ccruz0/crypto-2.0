"""Tests for approval queue monitor metrics and lifecycle."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.services.approval_queue_monitor import (
    collect_approval_queue_stats,
    collect_jarvis_approval_queue_stats,
    expire_stale_jarvis_waiting_approvals,
    expire_stale_pending_approvals,
    run_approval_queue_maintenance,
)


class TestApprovalQueueMonitor(unittest.TestCase):
    def test_collect_stats_marks_stale_pending(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=30)
        row_old = MagicMock(requested_at=old)
        row_new = MagicMock(requested_at=now - timedelta(hours=1))
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            row_old,
            row_new,
        ]
        stats = collect_approval_queue_stats(db, stale_hours=24)
        self.assertEqual(stats["pending_total"], 2)
        self.assertEqual(stats["stale_total"], 1)
        self.assertGreater(stats["oldest_pending_age_seconds"], 24 * 3600)

    def test_expire_stale_pending_approvals(self):
        now = datetime.now(timezone.utc)
        row = MagicMock(
            status="pending",
            requested_at=now - timedelta(days=10),
            execution_summary=None,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [row]
        expired = expire_stale_pending_approvals(db, expire_days=7)
        self.assertEqual(expired, 1)
        self.assertEqual(row.status, "expired")
        db.commit.assert_called_once()


class TestJarvisApprovalQueueMonitor(unittest.TestCase):
    def test_collect_jarvis_stats_marks_stale_waiting(self):
        now = datetime.now(timezone.utc)
        row_old = MagicMock()
        row_old._mapping = {
            "status": "waiting_for_approval",
            "created_at": now - timedelta(hours=30),
        }
        row_new = MagicMock()
        row_new._mapping = {
            "status": "waiting_for_pr_approval",
            "created_at": now - timedelta(hours=2),
        }
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [row_old, row_new]
        stats = collect_jarvis_approval_queue_stats(db, stale_hours=24)
        self.assertEqual(stats["waiting_total"], 2)
        self.assertEqual(stats["stale_total"], 1)
        self.assertGreater(stats["oldest_waiting_age_seconds"], 24 * 3600)

    def test_collect_jarvis_stats_empty_when_table_missing(self):
        db = MagicMock()
        db.execute.side_effect = Exception("no such table: jarvis_task_runs")
        stats = collect_jarvis_approval_queue_stats(db, stale_hours=24)
        self.assertEqual(stats["waiting_total"], 0)
        self.assertEqual(stats["stale_total"], 0)
        self.assertEqual(stats["oldest_waiting_age_seconds"], 0.0)

    def test_expire_stale_jarvis_waiting_approvals_cancels_low_risk(self):
        now = datetime.now(timezone.utc)
        row = MagicMock()
        row._mapping = {
            "task_id": "task-low-old",
            "status": "waiting_for_approval",
            "risk_level": "low",
            "created_at": now - timedelta(days=10),
        }
        update_result = MagicMock(rowcount=1)
        db = MagicMock()
        # First execute: SELECT; subsequent: UPDATE + INSERT
        db.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=[row])),
            update_result,
            MagicMock(),
        ]
        expired = expire_stale_jarvis_waiting_approvals(
            db, expire_days=7, risk_levels=("low",)
        )
        self.assertEqual(expired, 1)
        db.commit.assert_called_once()
        self.assertEqual(db.execute.call_count, 3)

    def test_expire_stale_jarvis_waiting_approvals_noop_when_none(self):
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = []
        expired = expire_stale_jarvis_waiting_approvals(db, expire_days=7)
        self.assertEqual(expired, 0)
        db.commit.assert_not_called()

    def test_run_maintenance_includes_jarvis_expired(self):
        db = MagicMock()
        # collect agent stats path
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        db.query.return_value.filter.return_value.all.return_value = []
        # jarvis collect + jarvis expire SELECT both return empty
        db.execute.return_value.fetchall.return_value = []
        out = run_approval_queue_maintenance(db)
        self.assertIn("jarvis_expired", out)
        self.assertEqual(out["jarvis_expired"], 0)
        self.assertEqual(out["expired"], 0)
