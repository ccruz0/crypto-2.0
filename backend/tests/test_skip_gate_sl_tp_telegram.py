"""Fill-time skip_gate=True must still send SL/TP Telegram (ALGO 2026-08-06)."""

from unittest.mock import MagicMock, patch

from app.services.exchange_sync import ExchangeSyncService


def test_skip_gate_still_sends_sl_tp_telegram():
    svc = ExchangeSyncService()
    db = MagicMock()

    impl = {
        "sl_result": {"order_id": "73817490102060694", "error": None},
        "tp_result": {"order_id": "73817490102060693", "error": None},
        "sl_price": 0.0783,
        "tp_price": 0.09,
        "oco_group_id": "oco_test",
        "sl_newly_created": True,
        "tp_newly_created": True,
        "skip_tp_creation": False,
        "skip_tp_reason": None,
    }

    with patch.object(svc, "_create_sl_tp_impl", return_value=impl) as create_impl, patch(
        "app.services.live_trading_gate.get_live_trading", return_value=True
    ), patch(
        "app.services.telegram_event_dedup.claim_telegram_event", return_value=True
    ) as claim, patch(
        "app.services.telegram_notifier.telegram_notifier"
    ) as notifier, patch(
        "app.models.watchlist.WatchlistItem"
    ):
        notifier.send_sl_tp_orders.return_value = True
        # Avoid watchlist DB query noise
        db.query.return_value.filter.return_value.first.return_value = None

        result = svc._create_sl_tp_for_filled_order(
            db=db,
            symbol="ALGO_USD",
            side="BUY",
            filled_price=0.08701,
            filled_qty=114.0,
            order_id="5755600492696996146",
            source="signal_monitor",
            skip_gate=True,
        )

    create_impl.assert_called_once()
    claim.assert_called()
    notifier.send_sl_tp_orders.assert_called_once()
    kwargs = notifier.send_sl_tp_orders.call_args.kwargs
    assert kwargs["symbol"] == "ALGO_USD"
    assert kwargs["sl_order_id"] == "73817490102060694"
    assert kwargs["tp_order_id"] == "73817490102060693"
    assert kwargs["original_order_id"] == "5755600492696996146"
    assert result["sl_result"]["order_id"] == "73817490102060694"


def test_skip_gate_skips_telegram_when_no_new_legs():
    svc = ExchangeSyncService()
    db = MagicMock()
    impl = {
        "status": "already_protected",
        "sl_result": {"order_id": "sl-existing", "error": None},
        "tp_result": {"order_id": "tp-existing", "error": None},
        "sl_price": 0.0783,
        "tp_price": 0.09,
        "sl_newly_created": False,
        "tp_newly_created": False,
    }
    with patch.object(svc, "_create_sl_tp_impl", return_value=impl), patch(
        "app.services.live_trading_gate.get_live_trading", return_value=True
    ), patch("app.services.telegram_notifier.telegram_notifier") as notifier:
        db.query.return_value.filter.return_value.first.return_value = None
        result = svc._create_sl_tp_for_filled_order(
            db=db,
            symbol="ALGO_USD",
            side="BUY",
            filled_price=0.08701,
            filled_qty=114.0,
            order_id="parent-already",
            source="signal_monitor",
            skip_gate=True,
        )
    notifier.send_sl_tp_orders.assert_not_called()
    assert result.get("status") == "already_protected"
