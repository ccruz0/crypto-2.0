"""Telegram ORDER EXECUTED origin must not falsely say Manual for bot fills."""
from unittest.mock import MagicMock

from app.services.telegram_notifier import TelegramNotifier


def _capture_origin(**kwargs) -> str:
    notifier = TelegramNotifier()
    sent = {}

    def _send(message, origin=None, **_k):
        sent["message"] = message
        return True

    notifier.send_message = _send  # type: ignore[method-assign]
    notifier.send_executed_order(
        symbol="APT_USD",
        side="SELL",
        price=0.5669,
        quantity=17.65,
        total_usd=10.01,
        order_id="5755600492526823562",
        order_type="MARKET",
        **kwargs,
    )
    return sent["message"]


def test_origin_alerta_when_trade_signal_id_present():
    msg = _capture_origin(trade_signal_id=42)
    assert "Alerta (Signal ID: 42)" in msg
    assert "Manual" not in msg


def test_origin_bot_when_system_attributed_without_signal_id():
    """OrderIntent race: bot placed order but TradeSignal link not visible yet."""
    msg = _capture_origin(system_attributed=True)
    assert "Bot / alerta ATP" in msg
    assert "Manual" not in msg


def test_origin_unlinked_does_not_claim_manual():
    msg = _capture_origin()
    assert "Sin señal vinculada" in msg
    assert "Manual" not in msg
