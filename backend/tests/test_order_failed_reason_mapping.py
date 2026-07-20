"""ORDER FAILED reason codes must not mislabel system_core blocks as EXCHANGE_ERROR_UNKNOWN."""

from app.utils.decision_reason import (
    ReasonCode,
    classify_exchange_error,
    format_order_failed_telegram,
    reason_code_es_label,
)


def test_one_active_trade_maps_to_specific_code():
    code = classify_exchange_error("system_core_one_active_trade_per_coin")
    assert code == ReasonCode.ONE_ACTIVE_TRADE_PER_COIN.value
    assert code != ReasonCode.EXCHANGE_ERROR_UNKNOWN.value


def test_telegram_copy_includes_spanish_per_coin_limit():
    code = ReasonCode.ONE_ACTIVE_TRADE_PER_COIN.value
    text = format_order_failed_telegram(
        symbol="BTC_USD",
        side="BUY",
        error_msg="system_core_one_active_trade_per_coin",
        reason_code=code,
    )
    assert "ONE_ACTIVE_TRADE_PER_COIN" in text
    assert "Máx. 1 trade activo" in text
    assert "per-coin" in text.lower() or "por moneda" in text.lower()
    assert "EXCHANGE_ERROR_UNKNOWN" not in text
    assert "Señal enviada" in text


def test_reason_code_es_label_one_active():
    label = reason_code_es_label(
        ReasonCode.ONE_ACTIVE_TRADE_PER_COIN.value,
        "system_core_one_active_trade_per_coin",
    )
    assert "trade activo" in label.lower() or "per-coin" in label.lower()


def test_max_open_trades_system_core():
    code = classify_exchange_error("system_core_max_open_trades count=10 max=10")
    assert code == ReasonCode.SYSTEM_CORE_MAX_OPEN_TRADES.value
