"""Regression test for the naked-TP-no-SL bug (2026-08 production incident).

Real production data (Postgres query, 2026-08-16/17) showed 46 of 50 unprotected
entry parents had a TAKE_PROFIT that was created and even FILLED, while STOP_LOSS
never existed at all. Code reading confirmed `_create_sl_tp_impl` always places
TP before SL on the margin/dual path (see [SLTP_DUAL_ORDER] log line), and the
try/except wrapping `_create_protection_after_entry_fill` at every call site in
signal_monitor.py has no flatten fallback if that call raises — so an unhandled
exception during SL placement (after TP already succeeded) would leave the
position with a live TP and no SL, and the hard "never leave a position without
a stop-loss" invariant would never fire because it lives inside the function
that raised.

This test locks in the fix: `_place_sl()` must never let an exception escape
`_create_sl_tp_impl` — any failure (returned error OR raised exception) must
surface as a normal `sl_result` dict with `error` set, so downstream callers
(and the flatten invariant in signal_monitor.py) see it as a normal failed
result rather than losing it to an unhandled exception.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.services.exchange_sync import ExchangeSyncService


def _watchlist_item(symbol="ATOM_USD"):
    wl = MagicMock()
    wl.symbol = symbol
    wl.sl_tp_mode = "conservative"
    wl.sl_percentage = None
    wl.tp_percentage = None
    return wl


class TestCreateSlTpImplSlException:
    def test_sl_exception_after_tp_success_does_not_propagate(self):
        """Margin dual path: TP succeeds, SL raises — must not escape as exception."""
        svc = ExchangeSyncService()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = _watchlist_item()

        with patch(
            "app.services.exchange_sync.get_active_protection_order",
            return_value=None,
        ), patch(
            "app.services.tp_sl_order_creator.resolve_sltp_margin_context",
            return_value=(True, 3.0),  # is_margin=True, matches _USD symbols seen in prod
        ), patch(
            "app.services.tp_sl_order_creator.is_native_oco_enabled",
            return_value=True,
        ), patch(
            "app.services.tp_sl_order_creator.create_take_profit_order",
            return_value={"order_id": "tp-live-123", "error": None},
        ), patch(
            "app.services.tp_sl_order_creator.create_stop_loss_order",
            side_effect=RuntimeError("simulated unhandled failure placing SL"),
        ), patch(
            "app.services.tp_sl_order_creator.is_insufficient_acc_balance_error",
            return_value=False,
        ):
            # Must not raise.
            result = svc._create_sl_tp_impl(
                db=db,
                symbol="ATOM_USD",
                side_upper="BUY",
                filled_price_f=10.0,
                filled_qty=5.0,
                order_id="parent-1",
                source="test",
                strict_percentages=False,
                sl_price_override_f=None,
                tp_price_override_f=None,
            )

        assert isinstance(result, dict)
        # TP succeeded and must be reflected as such.
        assert result["tp_result"]["order_id"] == "tp-live-123"
        assert not result["tp_result"]["error"]
        # SL must come back as a normal failed result, not an unhandled exception.
        assert result["sl_result"]["order_id"] is None
        assert result["sl_result"]["error"]
        assert "simulated unhandled failure placing SL" in result["sl_result"]["error"]
        assert result["sl_newly_created"] is False
