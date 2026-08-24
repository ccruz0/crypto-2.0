"""Human-readable Spanish messages for trading guardrail / system_core blocks."""

from __future__ import annotations

from app.utils.decision_reason import ReasonCode, classify_system_core_error

# Reason codes that should show a humanized Error line + technical detail.
_GUARDRAIL_FAMILY_CODES = frozenset(
    {
        ReasonCode.GUARDRAIL_BLOCKED.value,
        ReasonCode.ONE_ACTIVE_TRADE_PER_COIN.value,
        ReasonCode.SYSTEM_CORE_MAX_OPEN_TRADES.value,
        ReasonCode.SYSTEM_CORE_RSI.value,
        ReasonCode.SYSTEM_CORE_MA200.value,
        ReasonCode.SYSTEM_CORE_MAX_TRADE_USD.value,
        ReasonCode.SYSTEM_CORE_DAILY_DRAWDOWN.value,
        ReasonCode.INSTRUMENT_SHORT_SELL_DISABLED.value,
            ReasonCode.REGIME_FILTER_BLOCKED.value,
    }
)


def is_guardrail_family_reason(reason_code: str, error_msg: str | None = None) -> bool:
    if reason_code in _GUARDRAIL_FAMILY_CODES:
        return True
    return classify_system_core_error(error_msg or "") is not None


def humanize_guardrail_reason(
    reason: str,
    symbol: str | None = None,
    side: str = "BUY",
) -> str:
    """Map a raw guardrail reason string to a human-readable Spanish message."""
    base = (symbol or "la moneda").split("_")[0] if symbol else "la moneda"
    action = "Compra" if (side or "BUY").upper() == "BUY" else "Venta"
    r = (reason or "").lower()
    if "short_regime_price_above_ma200" in r:
        return (
            f"🛡️ {action} no ejecutada: no se abren cortos con el precio por "
            f"encima de su MA200 (tu regla del 22-ago). {base} esta en tendencia alcista."
        )
    if "long_btc_regime_btc_below_ma200" in r:
        return (
            f"🛡️ {action} no ejecutada: no se abren largos con BTC por debajo "
            f"de su MA200 (tu regla del 23-ago)."
        )
    if "short_regime_" in r or "long_btc_regime_" in r:
        return (
            f"🛡️ {action} no ejecutada: filtro de regimen sin datos validos "
            f"(fail-closed). No se envio nada al exchange."
        )
    if "one_active_trade_per_coin" in r:
        return (
            f"🚫 {action} no ejecutada: {base} ya tiene una posición abierta "
            f"(regla: 1 trade activo por moneda)."
        )
    if "max_open_trades" in r:
        return (
            f"🚫 {action} no ejecutada: alcanzado el máximo de posiciones "
            f"abiertas simultáneas."
        )
    if "max_trade_usd" in r:
        return f"🚫 {action} no ejecutada: el importe supera el máximo por operación."
    if "daily_drawdown" in r:
        return (
            f"🚫 {action} no ejecutada: alcanzado el límite de pérdida diaria "
            f"(drawdown)."
        )
    if "system_core_rsi" in r or r.startswith("system_core_rsi"):
        return f"🚫 {action} no ejecutada: RSI fuera del rango permitido."
    if "system_core_ma200" in r or r.startswith("system_core_ma200"):
        return f"🚫 {action} no ejecutada: el precio no cumple el filtro vs MA200."
    if (
        "instrument_short_sell" in r
        or "margin_sell_enabled" in r
        or "margin short sell" in r
        or "cannot_short_sell" in r
        or "cannot_short" in r
    ):
        return (
            f"🚫 {action} no ejecutada: {base} tiene Margin YES en watchlist, "
            f"pero el exchange no permite abrir SHORT (margen long sí). "
            f"No había long que cerrar."
        )
    if "max_orders_per_symbol_per_day" in r or "orders_today" in r:
        return f"🚫 {action} no ejecutada: {base} alcanzó el máximo de órdenes de hoy."
    return f"🚫 {action} no ejecutada: {reason}"


def order_failed_telegram_error_section(
    error_msg: str,
    symbol: str | None,
    reason_code: str,
    side: str = "BUY",
) -> tuple[str, str]:
    """
    Build user-facing ORDER FAILED error lines for Telegram.

    Returns (html_error_section, reason_message_for_storage).
    """
    if is_guardrail_family_reason(reason_code, error_msg):
        human = humanize_guardrail_reason(error_msg, symbol, side=side)
        section = f"{human}\n<i>Detalle técnico: {error_msg}</i>"
        return section, human
    return f"❌ Error: {error_msg}", error_msg


def order_failed_store_message(
    symbol: str,
    side: str,
    error_msg: str,
    reason_code: str,
    *,
    display_reason: str,
) -> str:
    """Flat message for telegram_messages DB row."""
    if is_guardrail_family_reason(reason_code, error_msg):
        base = (
            f"🛡️ ORDEN BLOQUEADA | {symbol} {side} | {display_reason} "
            f"| reason_code={reason_code}"
        )
        return f"{base} | tech={error_msg}"
    base = f"❌ ORDER FAILED | {symbol} {side} | {display_reason} | reason_code={reason_code}"
    if is_guardrail_family_reason(reason_code, error_msg):
        return f"{base} | tech={error_msg}"
    return base
