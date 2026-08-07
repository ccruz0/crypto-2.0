"""ORDER EXECUTED Telegram must tolerate Decimal qty/price from SQLAlchemy Numeric."""

from decimal import Decimal

from app.services.telegram_notifier import TelegramNotifier


def _capture(**kwargs) -> str:
    notifier = TelegramNotifier()
    sent = {}

    def _send(message, origin=None, **_k):
        sent["message"] = message
        return True

    notifier.send_message = _send  # type: ignore[method-assign]
    ok = notifier.send_executed_order(
        symbol="ALGO_USD",
        side="BUY",
        price=kwargs.get("price", Decimal("0.08701")),
        quantity=kwargs.get("quantity", Decimal("114.0")),
        total_usd=kwargs.get("total_usd", Decimal("9.919")),
        order_id="5755600492696996146",
        order_type=kwargs.get("order_type", "MARKET"),
        entry_price=kwargs.get("entry_price"),
        order_role=kwargs.get("order_role"),
        system_attributed=True,
    )
    assert ok is True
    return sent["message"]


def test_send_executed_order_accepts_decimal_qty_price():
    msg = _capture()
    assert "ORDER EXECUTED" in msg
    assert "ALGO_USD" in msg
    assert "114" in msg


def test_send_executed_order_tp_pnl_with_decimal_qty():
    """Regression: float entry_price * Decimal quantity raised TypeError (2026-08-06)."""
    msg = _capture(
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        entry_price=0.09,
        price=Decimal("0.08678"),
        quantity=Decimal("1312.0"),
        total_usd=Decimal("113.85"),
    )
    assert "ORDER EXECUTED" in msg
    assert "Take Profit" in msg
    assert "PROFIT" in msg or "LOSS" in msg
