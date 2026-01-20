from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.signal_throttle import SignalThrottleState

# Whitelisted fields that define alert/trading configuration for throttling resets
CONFIG_HASH_FIELDS = [
    "alert_enabled",
    "buy_alert_enabled",
    "sell_alert_enabled",
    "trade_enabled",
    "strategy_id",
    "strategy_name",
    "min_price_change_pct",
    "trade_amount_usd",
]


@dataclass
class SignalThrottleConfig:
    """Runtime configuration for throttling."""

    min_price_change_pct: float
    min_interval_minutes: float


@dataclass
class LastSignalSnapshot:
    """Represents the last recorded signal for a given side."""

    side: str
    price: Optional[float]
    timestamp: Optional[datetime]
    force_next_signal: bool = False
    config_hash: Optional[str] = None  # Hash of config when signal was last emitted


def _normalize_strategy_key(strategy_type: Optional[str], risk_approach: Optional[str]) -> str:
    strategy = (strategy_type or "unknown").lower()
    risk = (risk_approach or "unknown").lower()
    return f"{strategy}:{risk}"


def build_strategy_key(strategy_type, risk_approach) -> str:
    """Helper to build a consistent key using enums or plain strings."""
    strategy_value = getattr(strategy_type, "value", strategy_type)
    risk_value = getattr(risk_approach, "value", risk_approach)
    return _normalize_strategy_key(strategy_value, risk_value)


def compute_config_hash(config: Dict[str, object]) -> str:
    """Compute a stable hash from whitelisted config fields to avoid spurious resets."""
    normalized = []
    for field in CONFIG_HASH_FIELDS:
        normalized.append(f"{field}={config.get(field)!r}")
    payload = "|".join(normalized)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fetch_signal_states(
    db: Session, *, symbol: str, strategy_key: str
) -> Dict[str, LastSignalSnapshot]:
    """Return last signal snapshots for both BUY and SELL sides."""
    rows = (
        db.query(SignalThrottleState)
        .filter(
            SignalThrottleState.symbol == symbol,
            SignalThrottleState.strategy_key == strategy_key,
        )
        .all()
    )
    snapshots: Dict[str, LastSignalSnapshot] = {}
    for row in rows:
        snapshots[row.side.upper()] = LastSignalSnapshot(
            side=row.side.upper(),
            price=row.last_price,
            timestamp=row.last_time,
            force_next_signal=getattr(row, 'force_next_signal', False),
            config_hash=getattr(row, 'config_hash', None),
        )
    return snapshots


def _normalize_timestamp(ts: Optional[datetime]) -> Optional[datetime]:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def should_emit_signal(
    *,
    symbol: str,
    side: str,
    current_price: float,
    current_time: datetime,
    config: SignalThrottleConfig,
    last_same_side: Optional[LastSignalSnapshot],
    last_opposite_side: Optional[LastSignalSnapshot],
    db: Optional[Session] = None,
    strategy_key: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Core gate where we decide if a new logical signal (and thus alerts/orders) is allowed
    under the configured price-change and cooldown thresholds.
    
    If force_next_signal is set on last_same_side, this function will bypass throttling
    and return True with reason "FORCED_AFTER_TOGGLE_RESET". If db and strategy_key
    are provided, it will also clear the force flag.
    """
    side = side.upper()
    now_ts = _normalize_timestamp(current_time) or datetime.now(timezone.utc)
    
    # Check for force_next_signal flag first (bypasses all throttling once)
    if last_same_side and getattr(last_same_side, 'force_next_signal', False):
        # Clear the force flag from database if db and strategy_key are provided
        if db and strategy_key:
            try:
                existing = (
                    db.query(SignalThrottleState)
                    .filter(
                        SignalThrottleState.symbol == symbol,
                        SignalThrottleState.strategy_key == strategy_key,
                        SignalThrottleState.side == side,
                    )
                    .one_or_none()
                )
                if existing:
                    existing.force_next_signal = False
                    db.commit()
            except Exception as e:
                # Log but don't fail - throttle check should continue
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to clear force_next_signal for {symbol} {side}: {e}")
        return True, "IMMEDIATE_ALERT_AFTER_CONFIG_CHANGE"

    if last_same_side is None or last_same_side.timestamp is None or last_same_side.price is None:
        return True, "No previous same-side signal recorded"

    last_same_time = _normalize_timestamp(last_same_side.timestamp)
    if last_same_time is None:
        return True, "Previous same-side signal missing timestamp"

    # CANONICAL: Fixed 60 seconds (1.0 minute) throttling per (symbol, side)
    # BUY and SELL are independent - no reset on side change
    elapsed_seconds = (now_ts - last_same_time).total_seconds()
    FIXED_THROTTLE_SECONDS = 60.0  # Fixed by canonical logic (not configurable)
    time_gate_passed = elapsed_seconds >= FIXED_THROTTLE_SECONDS

    last_price = last_same_side.price
    if last_price and last_price > 0:
        price_change_pct = abs((current_price - last_price) / last_price * 100)
    else:
        price_change_pct = None
    # CRITICAL: Use explicit None check, not 'or' with floats (0.0 is valid threshold)
    min_pct = max(config.min_price_change_pct if config.min_price_change_pct is not None else 0.0, 0.0)
    price_required = min_pct > 0
    price_met = not price_required or (
        price_change_pct is not None and price_change_pct >= min_pct
    )

    # Time gate: Always check first (canonical: fixed 60 seconds)
    if not time_gate_passed:
        elapsed_minutes = elapsed_seconds / 60.0
        return (
            False,
            f"THROTTLED_TIME_GATE (elapsed {elapsed_seconds:.1f}s < {FIXED_THROTTLE_SECONDS:.0f}s)",
        )
    
    # Price gate: Only checked after time gate passes
    if not price_met and price_required:
        direction = "↑" if (last_price and current_price > last_price) else "↓" if last_price else ""
        return (
            False,
            f"THROTTLED_PRICE_GATE (absolute price change {direction} {(price_change_pct or 0.0):.2f}% < {min_pct:.2f}%)",
        )

    # Both gates passed
    elapsed_minutes = elapsed_seconds / 60.0
    summary_parts = [f"Δt={elapsed_seconds:.1f}s>= {FIXED_THROTTLE_SECONDS:.0f}s"]
    if price_required and price_change_pct is not None:
        direction = "↑" if (last_price and current_price > last_price) else "↓" if last_price else ""
        summary_parts.append(f"|Δp|={direction} {price_change_pct:.2f}%>= {min_pct:.2f}%")
    reason = " & ".join(summary_parts) if summary_parts else "No previous limits configured"
    return True, reason


def reset_throttle_state(
    db: Session,
    *,
    symbol: str,
    strategy_key: str,
    side: Optional[str] = None,
    current_price: Optional[float] = None,
    parameter_change_reason: Optional[str] = None,
    config_hash: Optional[str] = None,
) -> None:
    """
    Reset throttle state for a symbol+strategy combination (canonical: config change reset).
    If side is provided, only resets that side. Otherwise resets both BUY and SELL.
    
    CANONICAL BEHAVIOR (per ALERTAS_Y_ORDENES_NORMAS.md):
    - baseline_price := current_price_now (if provided) or None
    - last_sent_at is NOT updated on config change (only updated when an alert is SENT)
    - force_next_signal := True (to allow immediate bypass)
    
    If current_price is provided, it sets baseline_price to current price.
    Otherwise, it clears baseline_price (None) for a full reset.
    """
    symbol = symbol.upper()
    filters = [
        SignalThrottleState.symbol == symbol,
        SignalThrottleState.strategy_key == strategy_key,
    ]
    if side:
        filters.append(SignalThrottleState.side == side.upper())
    
    rows = db.query(SignalThrottleState).filter(*filters).all()
    
    try:
        for row in rows:
            # CANONICAL: On config change, set baseline_price to current_price (if provided)
            if current_price is not None and current_price > 0:
                row.last_price = current_price  # baseline_price = current_price_now
            else:
                row.last_price = None  # Full reset if no price provided
            row.previous_price = None
            # CANONICAL: Set force_next_signal = True to allow immediate bypass
            row.force_next_signal = True
            if parameter_change_reason:
                row.emit_reason = f"CONFIG_CHANGE_RESET_BASELINE: {parameter_change_reason}"
            if config_hash is not None:
                row.config_hash = config_hash
        db.commit()
    except Exception:
        db.rollback()
        raise


def set_force_next_signal(
    db: Session,
    *,
    symbol: str,
    strategy_key: str,
    side: str,
    enabled: bool = True,
) -> None:
    """
    Set or clear the force_next_signal flag for a specific symbol+strategy+side.
    When enabled, the next evaluation will bypass throttling once.
    """
    symbol = symbol.upper()
    side = side.upper()
    
    existing = (
        db.query(SignalThrottleState)
        .filter(
            SignalThrottleState.symbol == symbol,
            SignalThrottleState.strategy_key == strategy_key,
            SignalThrottleState.side == side,
        )
        .one_or_none()
    )
    
    try:
        if existing:
            existing.force_next_signal = enabled
        else:
            # Create a new record if it doesn't exist
            db.add(
                SignalThrottleState(
                    symbol=symbol,
                    strategy_key=strategy_key,
                    side=side,
                    force_next_signal=enabled,
                    last_time=datetime(1970, 1, 1, tzinfo=timezone.utc),  # Far past date
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise


def _build_emit_reason(
    *,
    throttle_reason: Optional[str],
    last_same_side: Optional[LastSignalSnapshot],
    last_opposite_side: Optional[LastSignalSnapshot],
    current_price: float,
    previous_price: Optional[float],
) -> str:
    """Build a comprehensive reason for why a signal was emitted."""
    reasons = []
    
    # Check if this is the first signal for this side
    if last_same_side is None or last_same_side.timestamp is None:
        reasons.append("First signal for this side/strategy")
    else:
        # Use the throttle reason if available
        if throttle_reason:
            reasons.append(throttle_reason)
        
        # Check for side change
        if last_opposite_side and last_opposite_side.timestamp:
            if last_opposite_side.timestamp > last_same_side.timestamp:
                reasons.append(f"Side change from {last_opposite_side.side} to {last_same_side.side}")
    
    # Add price change information if available
    if previous_price and previous_price > 0 and current_price > 0:
        price_change_pct = ((current_price - previous_price) / previous_price) * 100
        direction = "↑" if price_change_pct > 0 else "↓"
        reasons.append(f"Price change: {direction}{abs(price_change_pct):.2f}%")
    
    return " | ".join(reasons) if reasons else "Signal emitted"


def record_signal_event(
    db: Session,
    *,
    symbol: str,
    strategy_key: str,
    side: str,
    price: Optional[float],
    source: str,
    emit_reason: Optional[str] = None,
    config_hash: Optional[str] = None,
) -> None:
    """Persist the latest emitted signal."""
    side = side.upper()
    now_ts = datetime.now(timezone.utc)

    existing = (
        db.query(SignalThrottleState)
        .filter(
            SignalThrottleState.symbol == symbol,
            SignalThrottleState.strategy_key == strategy_key,
            SignalThrottleState.side == side,
        )
        .one_or_none()
    )

    try:
        if existing:
            # Save previous price before updating
            if existing.last_price is not None:
                existing.previous_price = existing.last_price
            existing.last_price = price
            existing.last_time = now_ts
            existing.last_source = source
            existing.emit_reason = emit_reason
            if config_hash is not None:
                existing.config_hash = config_hash
            # Clear force flag when recording a signal (it was used or we're recording new state)
            existing.force_next_signal = False
        else:
            db.add(
                SignalThrottleState(
                    symbol=symbol,
                    strategy_key=strategy_key,
                    side=side,
                    last_price=price,
                    last_time=now_ts,
                    last_source=source,
                    emit_reason=emit_reason,
                    force_next_signal=False,
                    config_hash=config_hash,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
