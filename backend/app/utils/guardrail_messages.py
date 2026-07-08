"""Human-readable Spanish messages for trading guardrail blocks."""

from __future__ import annotations

from app.utils.decision_reason import ReasonCode


def humanize_guardrail_reason(reason: str, symbol: str | None = None) -> str:
    """Map a raw guardrail reason string to a human-readable Spanish message."""
    base = (symbol or "la moneda").split("_")[0] if symbol else "la moneda"
    r = (reason or "").lower()
    if "one_active_trade_per_coin" in r:
        return (
            f"🚫 Compra no ejecutada: {base} ya tiene una posición abierta "
            f"(regla: 1 trade activo por moneda)."
        )
    if "max_open_trades" in r:
        return "🚫 Compra no ejecutada: alcanzado el máximo de posiciones abiertas simultáneas."
    if "max_trade_usd" in r:
        return "🚫 Compra no ejecutada: el importe supera el máximo por operación."
    if "daily_drawdown" in r:
        return "🚫 Compra no ejecutada: alcanzado el límite de pérdida diaria (drawdown)."
    if r.startswith("system_core_rsi"):
        return "🚫 Compra no ejecutada: RSI fuera del rango permitido para comprar."
    if "max_orders_per_symbol_per_day" in r or "orders_today" in r:
        return f"🚫 Compra no ejecutada: {base} alcanzó el máximo de órdenes de hoy."
    return f"🚫 Compra no ejecutada: {reason}"


def order_failed_telegram_error_section(
    error_msg: str,
    symbol: str | None,
    reason_code: str,
) -> tuple[str, str]:
    """
    Build user-facing ORDER FAILED error lines for Telegram.

    Returns (html_error_section, reason_message_for_storage).
    """
    if reason_code == ReasonCode.GUARDRAIL_BLOCKED.value:
        human = humanize_guardrail_reason(error_msg, symbol)
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
    base = f"❌ ORDER FAILED | {symbol} {side} | {display_reason} | reason_code={reason_code}"
    if reason_code == ReasonCode.GUARDRAIL_BLOCKED.value:
        return f"{base} | tech={error_msg}"
    return base
