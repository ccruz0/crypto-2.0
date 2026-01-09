"""DecisionReason helper for tracking buy order decisions"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from enum import Enum


class DecisionType(str, Enum):
    """Decision type: SKIPPED or FAILED"""
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class ReasonCode(str, Enum):
    """Canonical reason codes for buy decisions"""
    # Skip reasons
    TRADE_DISABLED = "TRADE_DISABLED"
    ALERT_DISABLED = "ALERT_DISABLED"
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
    
    # Fail reasons
    EXCHANGE_REJECTED = "EXCHANGE_REJECTED"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    SIGNATURE_ERROR = "SIGNATURE_ERROR"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    EXCHANGE_ERROR_UNKNOWN = "EXCHANGE_ERROR_UNKNOWN"


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


def classify_exchange_error(error_msg: str) -> str:
    """Classify exchange error into canonical reason code"""
    if not error_msg:
        return ReasonCode.EXCHANGE_ERROR_UNKNOWN.value
    
    error_upper = error_msg.upper()
    
    # Authentication errors
    if any(code in error_upper for code in ["401", "40101", "40103", "AUTHENTICATION"]):
        return ReasonCode.AUTHENTICATION_ERROR.value
    
    # Insufficient funds/balance
    if any(code in error_upper for code in ["306", "609", "INSUFFICIENT", "BALANCE", "MARGIN"]):
        if "609" in error_upper or "MARGIN" in error_upper:
            return ReasonCode.INSUFFICIENT_FUNDS.value  # Insufficient margin
        return ReasonCode.INSUFFICIENT_FUNDS.value
    
    # Rate limiting
    if any(code in error_upper for code in ["429", "RATE", "LIMIT", "TOO MANY"]):
        return ReasonCode.RATE_LIMIT.value
    
    # Timeout
    if any(code in error_upper for code in ["TIMEOUT", "TIMED OUT"]):
        return ReasonCode.TIMEOUT.value
    
    # Min notional
    if any(code in error_upper for code in ["MIN_NOTIONAL", "NOTIONAL", "AMOUNT TOO SMALL"]):
        return ReasonCode.MIN_NOTIONAL_NOT_MET.value
    
    # Signature errors
    if any(code in error_upper for code in ["SIGNATURE", "SIGN"]):
        return ReasonCode.SIGNATURE_ERROR.value
    
    # Generic rejection
    if any(code in error_upper for code in ["REJECTED", "REJECT"]):
        return ReasonCode.EXCHANGE_REJECTED.value
    
    # Default to unknown
    return ReasonCode.EXCHANGE_ERROR_UNKNOWN.value

