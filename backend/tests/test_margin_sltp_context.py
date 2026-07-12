"""Tests for margin-aware SL/TP context and half-protected backfill gate."""
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.services.exchange_sync import should_auto_create_sl_tp_on_sync
from app.services.tp_sl_order_creator import resolve_sltp_margin_context


class TestMarginSltpContext(unittest.TestCase):
    def test_resolve_margin_from_watchlist(self):
        db = MagicMock()
        item = MagicMock(trade_on_margin=True, leverage=5)
        db.query.return_value.filter.return_value.first.return_value = item
        is_margin, leverage = resolve_sltp_margin_context(db, "ETH_USD")
        self.assertTrue(is_margin)
        self.assertEqual(leverage, 5.0)

    def test_half_protected_backfill_bypasses_age_gate(self):
        db = MagicMock()
        order = MagicMock(
            exchange_order_id="parent-1",
            symbol="ETH_USD",
            trade_signal_id=None,
            parent_order_id=None,
        )
        now = datetime.now(timezone.utc)
        filled_time = now - timedelta(hours=48)

        sl = ExchangeOrder(exchange_order_id="sl-1", order_role="STOP_LOSS", status=OrderStatusEnum.ACTIVE)

        with patch("app.services.exchange_sync.link_system_trade_signal_to_order", return_value=False):
            with patch("app.services.exchange_sync.is_system_created_order", return_value=False):
                with patch("app.services.exchange_sync.has_complete_sl_tp_protection", return_value=False):
                    with patch(
                        "app.services.exchange_sync.get_active_protection_order",
                        side_effect=lambda _db, _parent, role: sl if role == "STOP_LOSS" else None,
                    ):
                        allowed, reason = should_auto_create_sl_tp_on_sync(
                            db, order, filled_time, now
                        )
        self.assertTrue(allowed)
        self.assertEqual(reason, "half_protected_backfill")


if __name__ == "__main__":
    unittest.main()
