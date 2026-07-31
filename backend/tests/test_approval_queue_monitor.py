"""Tests for approval queue monitor metrics and lifecycle."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.services.approval_queue_monitor import (
    collect_approval_queue_stats,
    collect_jarvis_approval_queue_stats,
    dedupe_jarvis_waiting_approvals,
    escalate_stale_jarvis_waiting_approvals,
    expire_stale_jarvis_waiting_approvals,
    expire_stale_pending_approvals,
    objective_fingerprint,
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

    def test_objective_fingerprint_normalizes_whitespace(self):
        a = objective_fingerprint("Fix  HostSwap")
        b = objective_fingerprint("fix hostswap")
        self.assertEqual(a, b)
        self.assertEqual(objective_fingerprint("  "), "")

    def test_dedupe_cancels_older_duplicate(self):
        now = datetime.now(timezone.utc)
        newer = MagicMock()
        newer._mapping = {
            "task_id": "task-new",
            "objective": "Fix HostSwap",
            "created_at": now,
        }
        older = MagicMock()
        older._mapping = {
            "task_id": "task-old",
            "objective": "fix  hostswap",
            "created_at": now - timedelta(hours=2),
        }
        db = MagicMock()
        db.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=[newer, older])),
            MagicMock(rowcount=1),  # UPDATE older
            MagicMock(),  # audit insert
        ]
        cancelled = dedupe_jarvis_waiting_approvals(db)
        self.assertEqual(cancelled, 1)
        db.commit.assert_called_once()

    def test_dedupe_keep_task_id_cancels_siblings(self):
        now = datetime.now(timezone.utc)
        keep = MagicMock()
        keep._mapping = {
            "task_id": "keep-me",
            "objective": "Same objective",
            "created_at": now - timedelta(hours=1),
        }
        other = MagicMock()
        other._mapping = {
            "task_id": "drop-me",
            "objective": "same objective",
            "created_at": now,
        }
        db = MagicMock()
        db.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=[other, keep])),
            MagicMock(rowcount=1),
            MagicMock(),
        ]
        cancelled = dedupe_jarvis_waiting_approvals(db, keep_task_id="keep-me")
        self.assertEqual(cancelled, 1)

    @patch.dict("os.environ", {"APPROVAL_QUEUE_JARVIS_DEDUP_ENABLED": "false"})
    def test_dedupe_disabled_via_env(self):
        db = MagicMock()
        self.assertEqual(dedupe_jarvis_waiting_approvals(db), 0)
        db.execute.assert_not_called()

    def test_run_maintenance_includes_jarvis_expired_and_deduped(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        db.query.return_value.filter.return_value.all.return_value = []
        db.execute.return_value.fetchall.return_value = []
        out = run_approval_queue_maintenance(db)
        self.assertIn("jarvis_expired", out)
        self.assertIn("jarvis_deduped", out)
        self.assertIn("jarvis_escalated", out)
        self.assertEqual(out["jarvis_expired"], 0)
        self.assertEqual(out["jarvis_deduped"], 0)
        self.assertEqual(out["jarvis_escalated"], 0)
        self.assertEqual(out["expired"], 0)

    @patch("app.services.telegram_notifier.telegram_notifier")
    def test_escalate_sends_ops_telegram_once(self, mock_notifier):
        now = datetime.now(timezone.utc)
        row = MagicMock()
        row._mapping = {
            "task_id": "task-high-old",
            "objective": "Ship risky change",
            "risk_level": "high",
            "created_at": now - timedelta(days=4),
            "status": "waiting_for_approval",
        }
        db = MagicMock()
        # SELECT candidates, SELECT already-escalated (empty), INSERT audit
        db.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=[row])),
            MagicMock(fetchall=MagicMock(return_value=[])),
            MagicMock(),
        ]
        mock_notifier.send_message.return_value = True
        n = escalate_stale_jarvis_waiting_approvals(
            db, escalate_days=3, risk_levels=("medium", "high")
        )
        self.assertEqual(n, 1)
        mock_notifier.send_message.assert_called_once()
        kwargs = mock_notifier.send_message.call_args.kwargs
        self.assertEqual(kwargs.get("chat_destination"), "ops")
        db.commit.assert_called_once()

    @patch("app.services.telegram_notifier.telegram_notifier")
    def test_escalate_skips_already_escalated(self, mock_notifier):
        now = datetime.now(timezone.utc)
        row = MagicMock()
        row._mapping = {
            "task_id": "task-med",
            "objective": "Already pinged",
            "risk_level": "medium",
            "created_at": now - timedelta(days=5),
            "status": "waiting_for_approval",
        }
        already = MagicMock()
        already._mapping = {"task_id": "task-med"}
        db = MagicMock()
        db.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=[row])),
            MagicMock(fetchall=MagicMock(return_value=[already])),
        ]
        n = escalate_stale_jarvis_waiting_approvals(db, escalate_days=3)
        self.assertEqual(n, 0)
        mock_notifier.send_message.assert_not_called()
        db.commit.assert_not_called()

    @patch.dict("os.environ", {"APPROVAL_QUEUE_JARVIS_ESCALATE_ENABLED": "false"})
    def test_escalate_disabled_via_env(self):
        db = MagicMock()
        self.assertEqual(escalate_stale_jarvis_waiting_approvals(db), 0)
        db.execute.assert_not_called()
