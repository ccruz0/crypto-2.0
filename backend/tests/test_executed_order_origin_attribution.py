"""Telegram ORDER EXECUTED origin must not falsely say Manual for bot fills."""

from app.services.telegram_notifier import TelegramNotifier


def _capture_origin(side: str = "SELL", **kwargs) -> str:
    notifier = TelegramNotifier()
    sent = {}

    def _send(message, origin=None, **_k):
        sent["message"] = message
        return True

    notifier.send_message = _send  # type: ignore[method-assign]
    notifier.send_executed_order(
        symbol="APT_USD",
        side=side,
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
    assert "Venta generada por alerta (Signal ID: 42)" in msg
    assert "Compra generada por alerta" not in msg
    assert "Manual" not in msg
    assert "Bot / alerta ATP" not in msg


def test_origin_compra_when_buy_trade_signal_id():
    msg = _capture_origin(side="BUY", trade_signal_id=7)
    assert "Compra generada por alerta (Signal ID: 7)" in msg
    assert "Venta generada por alerta" not in msg
    assert "Manual" not in msg


def test_origin_bot_when_system_attributed_without_signal_id():
    """OrderIntent race: bot placed order but TradeSignal link not visible yet."""
    msg = _capture_origin(system_attributed=True)
    assert "Venta generada por alerta" in msg
    assert "Bot / alerta ATP" not in msg
    assert "Manual" not in msg


def test_origin_compra_when_system_attributed_buy():
    msg = _capture_origin(side="BUY", system_attributed=True)
    assert "Compra generada por alerta" in msg
    assert "Venta generada por alerta" not in msg
    assert "Manual" not in msg


def test_origin_unlinked_does_not_claim_manual():
    msg = _capture_origin()
    assert "Sin señal vinculada" in msg
    assert "Manual" not in msg


def test_type_label_stop_loss_when_role_set_even_if_market():
    msg = _capture_origin(order_role="STOP_LOSS")
    assert "📋 Type: Stop Loss" in msg
    assert "Type: MARKET" not in msg
    assert "Stop Loss" in msg


def test_type_label_take_profit_when_role_set_even_if_market():
    msg = _capture_origin(order_role="TAKE_PROFIT")
    assert "📋 Type: Take Profit" in msg
    assert "Type: MARKET" not in msg


def test_type_label_keeps_market_for_orphan_manual_close():
    msg = _capture_origin()
    assert "📋 Type: MARKET" in msg
    assert "Type: Stop Loss" not in msg
    assert "Type: Take Profit" not in msg
