"""Tests for cross-process Telegram event deduplication and noise fixes."""
import unittest
from unittest.mock import MagicMock, patch

from app.services.telegram_event_dedup import (
    claim_telegram_event,
    clear_memory_claims_for_tests,
    is_telegram_event_claimed,
)


class TestTelegramEventDedupMemory(unittest.TestCase):
    def setUp(self):
        clear_memory_claims_for_tests()

    def tearDown(self):
        clear_memory_claims_for_tests()

    def test_first_claim_allows_second_suppresses(self):
        self.assertTrue(claim_telegram_event(None, "short_tp_not_widened:order-1", ttl_minutes=60))
        self.assertFalse(claim_telegram_event(None, "short_tp_not_widened:order-1", ttl_minutes=60))
        self.assertTrue(is_telegram_event_claimed(None, "short_tp_not_widened:order-1", ttl_minutes=60))

    def test_different_keys_independent(self):
        self.assertTrue(claim_telegram_event(None, "config_fail:amount_usd_missing:ETH_USD", ttl_minutes=60))
        self.assertTrue(claim_telegram_event(None, "config_fail:amount_usd_missing:BTC_USD", ttl_minutes=60))
        self.assertFalse(claim_telegram_event(None, "config_fail:amount_usd_missing:ETH_USD", ttl_minutes=60))


class TestSlTpReuseSkipsTelegram(unittest.TestCase):
    @patch("app.services.telegram_notifier.telegram_notifier")
    @patch("app.api.routes_signals.calculate_stop_loss_and_take_profit", create=True)
    @patch("app.services.exchange_sync.try_acquire_sl_tp_creation_lock", return_value=True)
    @patch("app.services.exchange_sync.release_sl_tp_creation_lock")
    @patch("app.services.live_trading_gate.get_live_trading", return_value=True)
    def test_no_new_protection_skips_telegram(
        self, _live, _release, _lock, _calc, mock_notifier
    ):
        from app.services.exchange_sync import ExchangeSyncService

        db = MagicMock()
        filled_count_query = MagicMock()
        filled_count_query.filter.return_value.count.return_value = 0
        db.query.return_value = filled_count_query

        svc = ExchangeSyncService()
        svc.sync_open_orders = MagicMock()
        svc._sl_tp_creation_locks = {}
        svc._create_sl_tp_impl = MagicMock(
            return_value={
                "sl_result": {"order_id": "sl-existing", "error": None},
                "tp_result": {
                    "order_id": None,
                    "error": "TP target already reached (cached skip)",
                    "error_code": "TP_TARGET_ALREADY_REACHED",
                },
                "sl_price": 1969.73,
                "tp_price": 1772.75,
                "oco_group_id": None,
                "skip_tp_creation": True,
                "skip_tp_reason": "TP_TARGET_ALREADY_REACHED",
                "sl_newly_created": False,
                "tp_newly_created": False,
                "status": "already_protected",
            }
        )

        with patch.dict("sys.modules", {"app.api.routes_signals": MagicMock()}):
            result = svc._create_sl_tp_for_filled_order(
                db=db,
                symbol="ETH_USD",
                side="SELL",
                filled_price=1790.66,
                filled_qty=0.0558,
                order_id="parent-1",
                source="test",
            )

        self.assertEqual(result.get("status"), "already_protected")
        mock_notifier.send_sl_tp_orders.assert_not_called()
        mock_notifier.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
