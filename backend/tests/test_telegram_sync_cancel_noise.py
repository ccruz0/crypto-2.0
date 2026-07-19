"""Dedup / suppress noisy sync-cancel and OCO health Telegram alerts."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.telegram_event_dedup import clear_memory_claims_for_tests


class TestSyncCancelTelegramNoise(unittest.TestCase):
    def setUp(self):
        clear_memory_claims_for_tests()

    def tearDown(self):
        clear_memory_claims_for_tests()

    def test_protection_legs_filtered_out(self):
        from app.services.exchange_sync import filter_sync_cancel_orders_for_telegram

        protection = SimpleNamespace(
            exchange_order_id="73817490102089963",
            symbol="ETH_USDT",
            order_role="STOP_LOSS",
        )
        entry = SimpleNamespace(
            exchange_order_id="5755600491252172536",
            symbol="ETH_USDT",
            order_role=None,
        )
        out = filter_sync_cancel_orders_for_telegram(None, [protection, entry])
        self.assertEqual([o.exchange_order_id for o in out], ["5755600491252172536"])

    def test_entry_cancel_deduped_by_order_id(self):
        from app.services.exchange_sync import filter_sync_cancel_orders_for_telegram

        entry = SimpleNamespace(
            exchange_order_id="entry-dup-1",
            symbol="ETH_USDT",
            order_role=None,
        )
        first = filter_sync_cancel_orders_for_telegram(None, [entry])
        second = filter_sync_cancel_orders_for_telegram(None, [entry])
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)


class TestOcoHealthTelegramDedup(unittest.TestCase):
    def setUp(self):
        clear_memory_claims_for_tests()

    def tearDown(self):
        clear_memory_claims_for_tests()

    @patch("app.services.sl_tp_checker.telegram_notifier")
    def test_identical_oco_health_suppressed_on_second_send(self, mock_notifier):
        from app.services.sl_tp_checker import SLTPCheckerService

        issues = {
            "total_oco_groups": 41,
            "orphaned_orders": [],
            "incomplete_groups": [
                {
                    "symbol": "ETH_USDT",
                    "missing": "STOP_LOSS",
                    "oco_group_id": "oco_abc",
                }
            ],
        }
        checker = SLTPCheckerService()
        self.assertEqual(checker._send_oco_alerts(issues, db=None), 1)
        mock_notifier.send_message.assert_called_once()
        self.assertEqual(checker._send_oco_alerts(issues, db=None), 0)
        self.assertEqual(mock_notifier.send_message.call_count, 1)

    @patch("app.services.sl_tp_checker.telegram_notifier")
    def test_changed_oco_fingerprint_allows_new_alert(self, mock_notifier):
        from app.services.sl_tp_checker import SLTPCheckerService

        checker = SLTPCheckerService()
        first = {
            "total_oco_groups": 41,
            "orphaned_orders": [],
            "incomplete_groups": [
                {"symbol": "ETH_USDT", "missing": "STOP_LOSS", "oco_group_id": "oco_1"}
            ],
        }
        second = {
            "total_oco_groups": 41,
            "orphaned_orders": [],
            "incomplete_groups": [
                {"symbol": "DOT_USD", "missing": "TAKE_PROFIT", "oco_group_id": "oco_2"}
            ],
        }
        self.assertEqual(checker._send_oco_alerts(first, db=None), 1)
        self.assertEqual(checker._send_oco_alerts(second, db=None), 1)
        self.assertEqual(mock_notifier.send_message.call_count, 2)


if __name__ == "__main__":
    unittest.main()
