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
    # 24-ago-2026: este bloqueo es una regla propia, no un fallo. El pie
    # "Senal enviada; la orden no se creo" era falso (nunca se envio nada al
    # exchange) y la cabecera decia ORDER FAILED. Ahora ambos son honestos.
    # Ver claude/atp-ordenes-fallando-24ago-veredicto.md.
    assert "ORDER FAILED" not in text
    assert "ORDEN BLOQUEADA POR REGLA PROPIA" in text
    assert "no se envio nada al exchange" in text.lower().replace("ó", "o")


def test_instrument_short_sell_disabled_not_insufficient_funds():
    msg = (
        "Watchlist Margin YES is on for CRO_USD, but Crypto.com does not "
        "allow opening a SHORT (margin_sell_enabled=false). A SELL alert "
        "always opens a new independent short; it does not close an existing long."
    )
    code = classify_exchange_error(msg)
    assert code == ReasonCode.INSTRUMENT_SHORT_SELL_DISABLED.value
    assert code != ReasonCode.INSUFFICIENT_FUNDS.value


def test_legacy_margin_short_sell_copy_not_insufficient_funds():
    msg = (
        "Exchange does not allow margin short sell for CRO_USD "
        "(margin_sell_enabled=false)"
    )
    code = classify_exchange_error(msg)
    assert code == ReasonCode.INSTRUMENT_SHORT_SELL_DISABLED.value
    assert code != ReasonCode.INSUFFICIENT_FUNDS.value


def test_instrument_short_sell_disabled_canonical_code():
    code = classify_exchange_error("INSTRUMENT_SHORT_SELL_DISABLED")
    assert code == ReasonCode.INSTRUMENT_SHORT_SELL_DISABLED.value


def test_instrument_short_sell_disabled_telegram_copy():
    msg = (
        "Watchlist Margin YES is on for CRO_USD, but Crypto.com does not "
        "allow opening a SHORT (margin_sell_enabled=false)."
    )
    code = classify_exchange_error(msg)
    text = format_order_failed_telegram(
        symbol="CRO_USD",
        side="SELL",
        error_msg=msg,
        reason_code=code,
    )
    assert "INSTRUMENT_SHORT_SELL_DISABLED" in text
    assert "INSUFFICIENT_FUNDS" not in text
    assert "short" in text.lower() or "SHORT" in text
    assert "watchlist" in text.lower() or "Margin YES" in text


def test_reason_code_es_label_one_active():
    label = reason_code_es_label(
        ReasonCode.ONE_ACTIVE_TRADE_PER_COIN.value,
        "system_core_one_active_trade_per_coin",
    )
    assert "trade activo" in label.lower() or "per-coin" in label.lower()


def test_max_open_trades_system_core():
    code = classify_exchange_error("system_core_max_open_trades count=10 max=10")
    assert code == ReasonCode.SYSTEM_CORE_MAX_OPEN_TRADES.value


def test_below_min_order_size_maps_clear_code():
    msg = "500 Server Error: BELOW_MIN_ORDER_SIZE (code: 415)"
    code = classify_exchange_error(msg)
    assert code == ReasonCode.BELOW_MIN_ORDER_SIZE.value
    assert code != ReasonCode.EXCHANGE_ERROR_UNKNOWN.value


def test_below_min_order_size_telegram_copy():
    msg = "500 Server Error: BELOW_MIN_ORDER_SIZE (code: 415)"
    code = classify_exchange_error(msg)
    text = format_order_failed_telegram(
        symbol="DOGE_USD",
        side="SELL",
        error_msg=msg,
        reason_code=code,
    )
    assert "BELOW_MIN_ORDER_SIZE" in text
    assert "Cantidad bajo el mínimo" in text
    assert "EXCHANGE_ERROR_UNKNOWN" not in text
    assert "Exchange Error Unknown" not in text
