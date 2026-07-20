"""DecisionReason helper for tracking buy order decisions"""
import re
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from enum import Enum


class DecisionType(str, Enum):
    """Decision type: SKIPPED, FAILED, or EXECUTED"""
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    EXECUTED = "EXECUTED"


class ReasonCode(str, Enum):
    """Canonical reason codes for buy decisions"""
    # Skip reasons
    TRADE_DISABLED = "TRADE_DISABLED"
    ALERTS_DISABLED = "ALERTS_DISABLED"
    ALERT_DISABLED = "ALERT_DISABLED"  # Alias for ALERTS_DISABLED
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    ALREADY_HAS_OPEN_ORDER = "ALREADY_HAS_OPEN_ORDER"
    MAX_OPEN_TRADES_REACHED = "MAX_OPEN_TRADES_REACHED"
    PRICE_ABOVE_BUY_TARGET = "PRICE_ABOVE_BUY_TARGET"
    PRICE_NOT_IN_RANGE = "PRICE_NOT_IN_RANGE"
    RSI_NOT_LOW_ENOUGH = "RSI_NOT_LOW_ENOUGH"
    STRATEGY_DISALLOWS_BUY = "STRATEGY_DISALLOWS_BUY"
    INSUFFICIENT_AVAILABLE_BALANCE = "INSUFFICIENT_AVAILABLE_BALANCE"
    MIN_NOTIONAL_NOT_MET = "MIN_NOTIONAL_NOT_MET"
    THROTTLED_DUPLICATE_ALERT = "THROTTLED_DUPLICATE_ALERT"
    DATA_MISSING = "DATA_MISSING"
    SAFETY_GUARD = "SAFETY_GUARD"
    NO_SIGNAL = "NO_SIGNAL"
    INVALID_TRADE_AMOUNT = "INVALID_TRADE_AMOUNT"
    RECENT_ORDERS_COOLDOWN = "RECENT_ORDERS_COOLDOWN"
    GUARDRAIL_BLOCKED = "GUARDRAIL_BLOCKED"
    # system_core position / exposure gates (not exchange errors)
    ONE_ACTIVE_TRADE_PER_COIN = "ONE_ACTIVE_TRADE_PER_COIN"
    SYSTEM_CORE_MAX_OPEN_TRADES = "SYSTEM_CORE_MAX_OPEN_TRADES"
    SYSTEM_CORE_RSI = "SYSTEM_CORE_RSI"
    SYSTEM_CORE_MA200 = "SYSTEM_CORE_MA200"
    SYSTEM_CORE_MAX_TRADE_USD = "SYSTEM_CORE_MAX_TRADE_USD"
    SYSTEM_CORE_DAILY_DRAWDOWN = "SYSTEM_CORE_DAILY_DRAWDOWN"
    ORDER_CREATION_LOCK = "ORDER_CREATION_LOCK"
    IDEMPOTENCY_BLOCKED = "IDEMPOTENCY_BLOCKED"
    MARGIN_ERROR_609_LOCK = "MARGIN_ERROR_609_LOCK"
    DECISION_PIPELINE_NOT_CALLED = "DECISION_PIPELINE_NOT_CALLED"
    SIGNAL_ID_MISSING = "SIGNAL_ID_MISSING"
    MISSING_ORDER_INTENT = "MISSING_ORDER_INTENT"
    TELEGRAM_API_ERROR = "TELEGRAM_API_ERROR"
    
    # Fail reasons
    EXCHANGE_REJECTED = "EXCHANGE_REJECTED"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    SIGNATURE_ERROR = "SIGNATURE_ERROR"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    EXCHANGE_ERROR_UNKNOWN = "EXCHANGE_ERROR_UNKNOWN"
    
    # Execute reasons
    EXEC_ORDER_PLACED = "EXEC_ORDER_PLACED"


@dataclass
class DecisionReason:
    """Structured decision reason for buy order attempts"""
    reason_code: str
    reason_message: str
    decision_type: DecisionType
    context: Dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"  # e.g., "precheck", "throttle", "exchange", "risk", "guardrail"
    correlation_id: Optional[str] = None
    alert_id: Optional[str] = None
    exchange_error: Optional[str] = None  # Raw exchange error snippet for FAILED decisions
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "reason_code": self.reason_code,
            "reason_message": self.reason_message,
            "decision_type": self.decision_type.value,
            "context": self.context,
            "source": self.source,
            "correlation_id": self.correlation_id,
            "alert_id": self.alert_id,
            "exchange_error": self.exchange_error,
        }


def make_skip(
    reason_code: str,
    message: str,
    context: Optional[Dict[str, Any]] = None,
    source: str = "precheck",
    correlation_id: Optional[str] = None,
    alert_id: Optional[str] = None,
) -> DecisionReason:
    """Create a SKIPPED decision reason"""
    return DecisionReason(
        reason_code=reason_code,
        reason_message=message,
        decision_type=DecisionType.SKIPPED,
        context=context or {},
        source=source,
        correlation_id=correlation_id,
        alert_id=alert_id,
    )


def make_fail(
    reason_code: str,
    message: str,
    context: Optional[Dict[str, Any]] = None,
    exchange_error: Optional[str] = None,
    source: str = "exchange",
    correlation_id: Optional[str] = None,
    alert_id: Optional[str] = None,
) -> DecisionReason:
    """Create a FAILED decision reason"""
    return DecisionReason(
        reason_code=reason_code,
        reason_message=message,
        decision_type=DecisionType.FAILED,
        context=context or {},
        source=source,
        correlation_id=correlation_id,
        alert_id=alert_id,
        exchange_error=exchange_error,
    )


def make_execute(
    reason_code: str,
    message: str,
    context: Optional[Dict[str, Any]] = None,
    source: str = "order_creation",
    correlation_id: Optional[str] = None,
    alert_id: Optional[str] = None,
) -> DecisionReason:
    """Create an EXECUTED decision reason"""
    return DecisionReason(
        reason_code=reason_code,
        reason_message=message,
        decision_type=DecisionType.EXECUTED,
        context=context or {},
        source=source,
        correlation_id=correlation_id,
        alert_id=alert_id,
    )


def _looks_like_telegram_api_error(error_msg: str) -> bool:
    """True when the error is a Telegram Bot API / delivery failure, not a trade guardrail."""
    lower = (error_msg or "").lower()
    if not lower:
        return False
    if "api.telegram.org" in lower or "telegram api error" in lower:
        return True
    if "telegram http" in lower or "[telegram_failed]" in lower:
        return True
    if "telegram" in lower and any(
        token in lower for token in ("bad request", "can't parse", "message is too long", "http 400", "http 429")
    ):
        return True
    return False


# Spanish (and short EN) labels for Telegram / daily summary — not exchange errors.
_REASON_CODE_ES_LABELS = {
    ReasonCode.ONE_ACTIVE_TRADE_PER_COIN.value: (
        "Máx. 1 trade activo por moneda (límite per-coin)"
    ),
    ReasonCode.SYSTEM_CORE_MAX_OPEN_TRADES.value: "Máx. trades abiertos (portfolio)",
    ReasonCode.SYSTEM_CORE_RSI.value: "RSI fuera de rango (system_core)",
    ReasonCode.SYSTEM_CORE_MA200.value: "Precio vs MA200 (system_core)",
    ReasonCode.SYSTEM_CORE_MAX_TRADE_USD.value: "Tope USD por trade (system_core)",
    ReasonCode.SYSTEM_CORE_DAILY_DRAWDOWN.value: "Drawdown diario (system_core)",
    ReasonCode.GUARDRAIL_BLOCKED.value: "Bloqueado por guardrail",
}


def classify_system_core_error(error_msg: str) -> Optional[str]:
    """Map system_core_* / blocked: strings to a specific reason code, else None."""
    if not error_msg:
        return None
    error_lower = error_msg.lower().strip()
    # Strip common wrappers so classification is robust.
    for prefix in ("blocked:", "error:", "order failed:"):
        if error_lower.startswith(prefix):
            error_lower = error_lower[len(prefix) :].strip()

    if "system_core_one_active_trade_per_coin" in error_lower:
        return ReasonCode.ONE_ACTIVE_TRADE_PER_COIN.value
    if "system_core_max_open_trades" in error_lower:
        return ReasonCode.SYSTEM_CORE_MAX_OPEN_TRADES.value
    if error_lower.startswith("system_core_rsi") or " system_core_rsi" in error_lower:
        return ReasonCode.SYSTEM_CORE_RSI.value
    if error_lower.startswith("system_core_ma200") or " system_core_ma200" in error_lower:
        return ReasonCode.SYSTEM_CORE_MA200.value
    if "system_core_max_trade_usd" in error_lower:
        return ReasonCode.SYSTEM_CORE_MAX_TRADE_USD.value
    if "system_core_daily_drawdown" in error_lower:
        return ReasonCode.SYSTEM_CORE_DAILY_DRAWDOWN.value
    if error_lower.startswith("system_core") or "system_core_" in error_lower:
        return ReasonCode.GUARDRAIL_BLOCKED.value
    return None


def reason_code_es_label(reason_code: str, error_msg: Optional[str] = None) -> str:
    """Human-readable Spanish label for Telegram ORDER FAILED / summaries."""
    if reason_code in _REASON_CODE_ES_LABELS:
        return _REASON_CODE_ES_LABELS[reason_code]
    mapped = classify_system_core_error(error_msg or "")
    if mapped and mapped in _REASON_CODE_ES_LABELS:
        return _REASON_CODE_ES_LABELS[mapped]
    if reason_code:
        return reason_code.replace("_", " ").title()
    return "Error desconocido"


def format_order_failed_telegram(
    *,
    symbol: str,
    side: str,
    error_msg: str,
    reason_code: str,
) -> str:
    """Telegram HTML body for ORDER FAILED — includes Spanish reason, not EXCHANGE_ERROR_UNKNOWN noise."""
    es = reason_code_es_label(reason_code, error_msg)
    return (
        f"❌ <b>ORDER FAILED</b>\n\n"
        f"📊 Symbol: <b>{symbol}</b>\n"
        f"🔄 Side: {side}\n"
        f"❌ Error: {error_msg}\n"
        f"📋 Reason Code: {reason_code}\n"
        f"🇪🇸 Motivo: {es}\n\n"
        f"<i>Señal enviada; la orden no se creó.</i>"
    )


def classify_exchange_error(error_msg: str) -> str:
    """Classify exchange or local block error into canonical reason code"""
    if not error_msg:
        return ReasonCode.EXCHANGE_ERROR_UNKNOWN.value

    error_lower = error_msg.lower()

    # Telegram delivery failures must not be labeled as trading guardrails.
    if _looks_like_telegram_api_error(error_msg):
        return ReasonCode.TELEGRAM_API_ERROR.value

    system_core_code = classify_system_core_error(error_msg)
    if system_core_code:
        return system_core_code

    if error_lower.startswith("blocked:"):
        return ReasonCode.GUARDRAIL_BLOCKED.value
    if "guardrail" in error_lower or "trade_blocked" in error_lower:
        return ReasonCode.GUARDRAIL_BLOCKED.value

    error_upper = error_msg.upper()

    # Authentication errors (word-boundary style; avoid matching "401" inside bot tokens/URLs)
    if "AUTHENTICATION" in error_upper or "40101" in error_upper or "40103" in error_upper:
        return ReasonCode.AUTHENTICATION_ERROR.value
    if re.search(r"(?:^|[^0-9])401(?:[^0-9]|$)", error_msg):
        return ReasonCode.AUTHENTICATION_ERROR.value
    
    # Insufficient funds/balance
    if any(code in error_upper for code in ["306", "609", "INSUFFICIENT", "BALANCE", "MARGIN"]):
        if "609" in error_upper or "MARGIN" in error_upper:
            return ReasonCode.INSUFFICIENT_FUNDS.value  # Insufficient margin
        return ReasonCode.INSUFFICIENT_FUNDS.value
    
    # Rate limiting
    if any(code in error_upper for code in ["429", "RATE LIMIT", "TOO MANY"]):
        return ReasonCode.RATE_LIMIT.value
    if re.search(r"(?:^|[^0-9])429(?:[^0-9]|$)", error_msg):
        return ReasonCode.RATE_LIMIT.value
    
    # Timeout
    if any(code in error_upper for code in ["TIMEOUT", "TIMED OUT"]):
        return ReasonCode.TIMEOUT.value
    
    # Min notional
    if any(code in error_upper for code in ["MIN_NOTIONAL", "NOTIONAL", "AMOUNT TOO SMALL"]):
        return ReasonCode.MIN_NOTIONAL_NOT_MET.value
    
    # Signature errors (avoid bare "SIGN" — false-positives on SYSTEM_CORE etc.)
    if "SIGNATURE" in error_upper or re.search(r"(?:^|[^A-Z])SIGN(?:[^A-Z]|$)", error_upper):
        return ReasonCode.SIGNATURE_ERROR.value
    
    # Generic rejection
    if any(code in error_upper for code in ["REJECTED", "REJECT"]):
        return ReasonCode.EXCHANGE_REJECTED.value
    
    # Default to unknown
    return ReasonCode.EXCHANGE_ERROR_UNKNOWN.value
