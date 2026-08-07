"""Focused tests for create-protection-smart Telegram notify helper."""
import unittest
from unittest.mock import MagicMock, patch

from app.api.routes_orders import _notify_create_protection_smart_telegram


class TestNotifyCreateProtectionSmartTelegram(unittest.TestCase):
    def test_noop_when_created_empty(self):
        db = MagicMock()
        with patch(
            "app.services.telegram_event_dedup.claim_telegram_event"
        ) as claim, patch(
            "app.services.telegram_notifier.telegram_notifier"
        ) as notifier:
            _notify_create_protection_smart_telegram(
                db,
                symbol="ETH_USD",
                order_id="parent-1",
                entry_side="BUY",
                entry_price=2000.0,
                quantity=0.1,
                sl_price=1900.0,
                tp_price=2100.0,
                sl_pct=5.0,
                tp_pct=5.0,
                mode="conservative",
                created=[],
            )
            claim.assert_not_called()
            notifier.send_sl_tp_orders.assert_not_called()

    @patch("app.services.telegram_notifier.telegram_notifier")
    @patch("app.services.telegram_event_dedup.claim_telegram_event", return_value=True)
    def test_sends_both_legs_with_base_claim(self, mock_claim, mock_notifier):
        db = MagicMock()
        _notify_create_protection_smart_telegram(
            db,
            symbol="ETH_USD",
            order_id="parent-1",
            entry_side="BUY",
            entry_price=2000.0,
            quantity=0.1,
            sl_price=1900.0,
            tp_price=2100.0,
            sl_pct=5.0,
            tp_pct=5.0,
            mode="conservative",
            created=[
                {"role": "TAKE_PROFIT", "order_id": "tp-new", "price": 2100.0},
                {"role": "STOP_LOSS", "order_id": "sl-new", "price": 1900.0},
            ],
        )
        mock_claim.assert_called_once_with(
            db,
            "sl_tp_created:parent-1",
            symbol="ETH_USD",
            ttl_minutes=7 * 24 * 60,
            action="sl_tp_created",
        )
        mock_notifier.send_sl_tp_orders.assert_called_once()
        kwargs = mock_notifier.send_sl_tp_orders.call_args.kwargs
        self.assertEqual(kwargs["sl_order_id"], "sl-new")
        self.assertEqual(kwargs["tp_order_id"], "tp-new")
        self.assertTrue(kwargs["sl_newly_created"])
        self.assertTrue(kwargs["tp_newly_created"])
        self.assertEqual(kwargs["sl_side"], "SELL")
        self.assertEqual(kwargs["tp_side"], "SELL")

    @patch("app.services.telegram_notifier.telegram_notifier")
    @patch("app.services.telegram_event_dedup.claim_telegram_event", return_value=True)
    def test_tp_only_reuses_existing_sl_and_tp_ok_claim(self, mock_claim, mock_notifier):
        db = MagicMock()
        _notify_create_protection_smart_telegram(
            db,
            symbol="ETH_USD",
            order_id="parent-1",
            entry_side="BUY",
            entry_price=2000.0,
            quantity=0.1,
            sl_price=1900.0,
            tp_price=2100.0,
            sl_pct=5.0,
            tp_pct=5.0,
            mode="aggressive",
            created=[{"role": "TAKE_PROFIT", "order_id": "tp-new", "price": 2100.0}],
            existing_sl_id="sl-existing",
            existing_tp_id=None,
        )
        mock_claim.assert_called_once_with(
            db,
            "sl_tp_created:parent-1:tp_ok",
            symbol="ETH_USD",
            ttl_minutes=7 * 24 * 60,
            action="sl_tp_created",
        )
        kwargs = mock_notifier.send_sl_tp_orders.call_args.kwargs
        self.assertEqual(kwargs["sl_order_id"], "sl-existing")
        self.assertEqual(kwargs["tp_order_id"], "tp-new")
        self.assertFalse(kwargs["sl_newly_created"])
        self.assertTrue(kwargs["tp_newly_created"])

    @patch("app.services.telegram_notifier.telegram_notifier")
    @patch("app.services.telegram_event_dedup.claim_telegram_event", return_value=True)
    def test_sl_only_uses_sl_ok_claim(self, mock_claim, mock_notifier):
        db = MagicMock()
        _notify_create_protection_smart_telegram(
            db,
            symbol="BTC_USD",
            order_id="parent-2",
            entry_side="SELL",
            entry_price=50000.0,
            quantity=0.01,
            sl_price=52000.0,
            tp_price=48000.0,
            sl_pct=4.0,
            tp_pct=4.0,
            mode="conservative",
            created=[{"role": "STOP_LOSS", "order_id": "sl-new", "price": 52000.0}],
            existing_tp_id="tp-existing",
        )
        mock_claim.assert_called_once_with(
            db,
            "sl_tp_created:parent-2:sl_ok",
            symbol="BTC_USD",
            ttl_minutes=7 * 24 * 60,
            action="sl_tp_created",
        )
        kwargs = mock_notifier.send_sl_tp_orders.call_args.kwargs
        self.assertEqual(kwargs["sl_order_id"], "sl-new")
        self.assertEqual(kwargs["tp_order_id"], "tp-existing")
        self.assertTrue(kwargs["sl_newly_created"])
        self.assertFalse(kwargs["tp_newly_created"])
        self.assertEqual(kwargs["sl_side"], "BUY")

    @patch("app.services.telegram_notifier.telegram_notifier")
    @patch("app.services.telegram_event_dedup.claim_telegram_event", return_value=False)
    def test_skips_send_when_claim_denied(self, mock_claim, mock_notifier):
        db = MagicMock()
        _notify_create_protection_smart_telegram(
            db,
            symbol="ETH_USD",
            order_id="parent-1",
            entry_side="BUY",
            entry_price=2000.0,
            quantity=0.1,
            sl_price=1900.0,
            tp_price=2100.0,
            sl_pct=5.0,
            tp_pct=5.0,
            mode="conservative",
            created=[{"role": "STOP_LOSS", "order_id": "sl-new", "price": 1900.0}],
        )
        mock_claim.assert_called_once()
        mock_notifier.send_sl_tp_orders.assert_not_called()

    @patch("app.services.telegram_event_dedup.claim_telegram_event", side_effect=RuntimeError("boom"))
    def test_swallows_notify_errors(self, _mock_claim):
        db = MagicMock()
        # Must not raise
        _notify_create_protection_smart_telegram(
            db,
            symbol="ETH_USD",
            order_id="parent-1",
            entry_side="BUY",
            entry_price=2000.0,
            quantity=0.1,
            sl_price=1900.0,
            tp_price=2100.0,
            sl_pct=5.0,
            tp_pct=5.0,
            mode="conservative",
            created=[{"role": "STOP_LOSS", "order_id": "sl-new", "price": 1900.0}],
        )


if __name__ == "__main__":
    unittest.main()
