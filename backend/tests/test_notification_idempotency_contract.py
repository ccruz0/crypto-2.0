"""
PR11 / A4: Notification idempotency contract.

Ensures exactly-once terminal notifications per (order, terminal_status):
- Idempotency key is persisted on ExchangeOrder (last_notified_terminal_status).
- notify_on_terminal_transition checks before send and persists after send.
- Second call for same (order, status) does not send (at most one Telegram per transition).
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum


# --- Contract: model has idempotency key ---


def test_exchange_order_has_last_notified_terminal_status():
    """A4: ExchangeOrder must have last_notified_terminal_status for idempotent terminal notifications."""
    assert hasattr(ExchangeOrder, "last_notified_terminal_status")


# --- Contract: notifier checks before send (source) ---


def test_terminal_notifier_source_checks_last_notified_before_send():
    """A4: notify_on_terminal_transition must check last_notified_terminal_status before sending."""
    backend_root = Path(__file__).resolve().parent.parent
    notifier_path = backend_root / "app" / "services" / "terminal_order_notifier.py"
    text = notifier_path.read_text()
    assert "last_notified_terminal_status" in text, (
        "terminal_order_notifier must use last_notified_terminal_status for idempotency"
    )
    assert "last_notified" in text or "last_notified_terminal_status" in text
    assert "send_message" in text


# --- Contract: same (order, terminal_status) → at most one send ---


@patch("app.services.telegram_notifier.telegram_notifier", new_callable=MagicMock)
def test_notification_idempotency_second_call_same_status_does_not_send(mock_telegram):
    """A4: Second call for same order and same terminal status must not send (exactly-once)."""
    mock_telegram.send_message.return_value = True
    from app.services.terminal_order_notifier import notify_on_terminal_transition

    db = MagicMock()
    order_id = "ord-idempotent-1"
    # First call: not yet notified → sends
    order_first = MagicMock(spec=ExchangeOrder)
    order_first.exchange_order_id = order_id
    order_first.symbol = "BTC_USDT"
    order_first.side = OrderSideEnum.BUY
    order_first.status = OrderStatusEnum.CANCELLED
    order_first.last_notified_terminal_status = None
    order_first.price = 50000.0
    order_first.quantity = 0.001
    order_first.order_type = "LIMIT"
    order_first.order_role = None

    result1 = notify_on_terminal_transition(
        db=db,
        order=order_first,
        old_status=OrderStatusEnum.NEW,
        new_status=OrderStatusEnum.CANCELLED,
        reason="Order cancelled",
        status_source="sync",
    )
    assert result1 is True
    assert mock_telegram.send_message.call_count == 1

    # Second call: same logical transition (e.g. second sync) with state already persisted
    order_second = MagicMock(spec=ExchangeOrder)
    order_second.exchange_order_id = order_id
    order_second.symbol = "BTC_USDT"
    order_second.side = OrderSideEnum.BUY
    order_second.status = OrderStatusEnum.CANCELLED
    order_second.last_notified_terminal_status = "CANCELLED"  # Already notified
    order_second.price = 50000.0
    order_second.quantity = 0.001
    order_second.order_type = "LIMIT"
    order_second.order_role = None

    result2 = notify_on_terminal_transition(
        db=db,
        order=order_second,
        old_status=OrderStatusEnum.NEW,
        new_status=OrderStatusEnum.CANCELLED,
        reason="Order cancelled",
        status_source="sync",
    )
    assert result2 is False
    assert mock_telegram.send_message.call_count == 1, (
        "A4 idempotency: second call for same (order_id, terminal_status) must not send"
    )
