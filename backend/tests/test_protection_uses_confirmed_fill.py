"""Hot-path TP latency: reuse confirmed fill; do not re-poll."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.services.signal_monitor import SignalMonitorService


def _db_no_existing_protection():
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.all.return_value = []  # no existing SL/TP
    return db


def test_create_protection_skips_repoll_when_filled_confirmation_provided():
    svc = SignalMonitorService.__new__(SignalMonitorService)
    db = _db_no_existing_protection()

    confirmed = {
        "status": "FILLED",
        "cumulative_quantity": Decimal("0.103"),
        "avg_price": 96.812,
        "filled_price": 96.812,
    }

    with patch.object(svc, "_poll_order_fill_confirmation") as mock_poll, patch(
        "app.services.signal_monitor.trade_client"
    ) as mock_trade, patch(
        "app.services.exchange_sync.exchange_sync_service"
    ) as mock_sync, patch.object(
        svc, "_flatten_unprotected_entry"
    ):
        mock_trade.normalize_quantity_safe_with_fallback.return_value = (
            "0.103",
            {},
        )
        mock_sync._create_sl_tp_for_filled_order.return_value = {
            "sl_order_id": "sl-1",
            "tp_order_id": "tp-1",
            "status": "ok",
        }

        # Raw placement often lacks fill qty — would have triggered a second poll.
        result = svc._create_protection_after_entry_fill(
            db=db,
            symbol="AAVE_USD",
            entry_side="BUY",
            order_id="5755600492313745241",
            placement_result={"status": "NEW", "order_id": "5755600492313745241"},
            estimated_price=96.812,
            source="test",
            filled_confirmation=confirmed,
        )

    mock_poll.assert_not_called()
    mock_sync._create_sl_tp_for_filled_order.assert_called_once()
    assert result is not None


def test_create_protection_polls_when_confirmation_missing():
    svc = SignalMonitorService.__new__(SignalMonitorService)
    db = _db_no_existing_protection()

    with patch.object(
        svc,
        "_poll_order_fill_confirmation",
        return_value={
            "status": "FILLED",
            "cumulative_quantity": Decimal("0.1"),
            "avg_price": 10.0,
            "filled_price": 10.0,
        },
    ) as mock_poll, patch(
        "app.services.signal_monitor.trade_client"
    ) as mock_trade, patch(
        "app.services.exchange_sync.exchange_sync_service"
    ) as mock_sync, patch.object(
        svc, "_flatten_unprotected_entry"
    ):
        mock_trade.normalize_quantity_safe_with_fallback.return_value = ("0.1", {})
        mock_sync._create_sl_tp_for_filled_order.return_value = {"status": "ok"}

        svc._create_protection_after_entry_fill(
            db=db,
            symbol="AAVE_USD",
            entry_side="BUY",
            order_id="order-1",
            placement_result={"status": "NEW"},
            estimated_price=10.0,
            source="test",
            filled_confirmation=None,
        )

    mock_poll.assert_called_once()
