"""ORDER EXECUTED for SL/TP fills must notify once across repeated sync."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.services.exchange_sync import (
    ExchangeSyncService,
    _claim_order_executed_telegram,
    _mark_execution_notified_after_send,
)
from app.services.telegram_event_dedup import clear_memory_claims_for_tests


def _sl_order(*, order_id="73817490102060532"):
    order = MagicMock()
    order.exchange_order_id = order_id
    order.symbol = "HBAR_USD"
    order.side = MagicMock()
    order.side.value = "BUY"
    order.order_type = "STOP_LIMIT"
    order.order_role = "STOP_LOSS"
    order.parent_order_id = "5755600492576879706"
    order.trade_signal_id = None
    order.avg_price = 0.069
    order.price = 0.069
    order.quantity = 56.0
    order.cumulative_quantity = 56.0
    order.execution_notified_at = None
    order.exchange_update_time = datetime(2026, 8, 6, 15, 31, 30, tzinfo=timezone.utc)
    order.exchange_create_time = datetime(2026, 8, 6, 9, 2, 13, tzinfo=timezone.utc)
    return order


def test_claim_order_executed_memory_dedupes():
    clear_memory_claims_for_tests()
    with patch("app.services.exchange_sync.SessionLocal", None):
        assert _claim_order_executed_telegram("oid-once", symbol="HBAR_USD") is True
        assert _claim_order_executed_telegram("oid-once", symbol="HBAR_USD") is False


def test_mark_execution_notified_does_not_flush_outer_session():
    order = _sl_order()
    fill_dedup = MagicMock()
    with patch(
        "app.services.exchange_sync._persist_execution_notified_at"
    ) as persist:
        _mark_execution_notified_after_send(
            order,
            fill_dedup=fill_dedup,
            fill_qty=56.0,
            fill_status="FILLED",
        )
    assert order.execution_notified_at is not None
    persist.assert_called_once()
    fill_dedup.record_fill.assert_called_once_with(
        order_id="73817490102060532",
        filled_qty=56.0,
        status="FILLED",
        notification_sent=True,
    )


def test_repeated_sync_same_filled_sl_notifies_once():
    """Simulate resolve + history sync retrying the same FILLED protection order."""
    svc = ExchangeSyncService()
    order = _sl_order()
    db = MagicMock()
    fill_dedup = MagicMock()
    fill_dedup.should_notify_fill.return_value = (True, "First fill for this order")
    notifier = MagicMock()
    notifier.send_executed_order.return_value = True

    claim_results = iter([True, False, False])

    with patch(
        "app.services.exchange_sync.should_notify_executed_fill",
        return_value=(True, "system order"),
    ), patch(
        "app.services.exchange_sync.get_fill_dedup",
        return_value=fill_dedup,
    ), patch(
        "app.services.exchange_sync._count_open_entry_buy_orders",
        return_value=0,
    ), patch(
        "app.services.exchange_sync.ensure_system_order_attribution",
        return_value=(None, True, "parent_order_id"),
    ), patch(
        "app.services.exchange_sync._claim_order_executed_telegram",
        side_effect=lambda *a, **k: next(claim_results),
    ), patch(
        "app.services.exchange_sync._persist_execution_notified_at",
    ) as persist, patch(
        "app.services.telegram_notifier.telegram_notifier",
        notifier,
    ), patch.object(
        svc, "_infer_protection_order_role", return_value="STOP_LOSS"
    ), patch.object(
        svc, "_lookup_entry_price_for_protection", return_value=0.0696
    ):
        ok1 = svc._maybe_notify_executed_fill_telegram(
            db,
            order,
            source="sync_open_orders_resolve",
            price=0.069,
            quantity=56.0,
            status_str="FILLED",
        )
        assert ok1 is True
        assert order.execution_notified_at is not None
        assert notifier.send_executed_order.call_count == 1

        # Second sync still sees gate open (execution_notified_at wiped by outer
        # rollback) — claim must block re-send.
        order.execution_notified_at = None
        ok2 = svc._maybe_notify_executed_fill_telegram(
            db,
            order,
            source="exchange_sync.update_existing_order",
            price=0.069,
            quantity=56.0,
            status_str="FILLED",
        )
        ok3 = svc._maybe_notify_executed_fill_telegram(
            db,
            order,
            source="sync_open_orders_resolve",
            price=0.069,
            quantity=56.0,
            status_str="FILLED",
        )

    assert ok2 is False
    assert ok3 is False
    assert notifier.send_executed_order.call_count == 1
    persist.assert_called_once()


def test_claim_denied_skips_send_without_persist():
    svc = ExchangeSyncService()
    order = _sl_order(order_id="already-claimed")
    fill_dedup = MagicMock()
    fill_dedup.should_notify_fill.return_value = (True, "First fill for this order")
    notifier = MagicMock()

    with patch(
        "app.services.exchange_sync.should_notify_executed_fill",
        return_value=(True, "system order"),
    ), patch(
        "app.services.exchange_sync.get_fill_dedup",
        return_value=fill_dedup,
    ), patch(
        "app.services.exchange_sync._count_open_entry_buy_orders",
        return_value=0,
    ), patch(
        "app.services.exchange_sync.ensure_system_order_attribution",
        return_value=(None, True, "parent_order_id"),
    ), patch(
        "app.services.exchange_sync._claim_order_executed_telegram",
        return_value=False,
    ), patch(
        "app.services.exchange_sync._persist_execution_notified_at",
    ) as persist, patch(
        "app.services.telegram_notifier.telegram_notifier",
        notifier,
    ), patch.object(
        svc, "_infer_protection_order_role", return_value="STOP_LOSS"
    ), patch.object(
        svc, "_lookup_entry_price_for_protection", return_value=0.0696
    ):
        ok = svc._maybe_notify_executed_fill_telegram(
            MagicMock(),
            order,
            source="sync_open_orders_resolve",
            price=0.069,
            quantity=56.0,
            status_str="FILLED",
        )

    assert ok is False
    notifier.send_executed_order.assert_not_called()
    persist.assert_not_called()
