"""Tests for approval queue monitor metrics and lifecycle."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.services.approval_queue_monitor import (
    collect_approval_queue_stats,
    expire_stale_pending_approvals,
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
