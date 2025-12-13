from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.signal_throttle import SignalThrottleState


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


def _normalize_strategy_key(strategy_type: Optional[str], risk_approach: Optional[str]) -> str:
    strategy = (strategy_type or "unknown").lower()
    risk = (risk_approach or "unknown").lower()
    return f"{strategy}:{risk}"


def build_strategy_key(strategy_type, risk_approach) -> str:
    """Helper to build a consistent key using enums or plain strings."""
    strategy_value = getattr(strategy_type, "value", strategy_type)
    risk_value = getattr(risk_approach, "value", risk_approach)
    return _normalize_strategy_key(strategy_value, risk_value)


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
) -> Tuple[bool, str]:
    """
    Core gate where we decide if a new logical signal (and thus alerts/orders) is allowed
    under the configured price-change and cooldown thresholds.
    """
    side = side.upper()
    now_ts = _normalize_timestamp(current_time) or datetime.now(timezone.utc)

    if last_same_side is None or last_same_side.timestamp is None or last_same_side.price is None:
        return True, "No previous same-side signal recorded"

    last_same_time = _normalize_timestamp(last_same_side.timestamp)
    if last_same_time is None:
        return True, "Previous same-side signal missing timestamp"

    # Direction change resets throttling (BUY after SELL or vice versa)
    if last_opposite_side and last_opposite_side.timestamp:
        opposite_time = _normalize_timestamp(last_opposite_side.timestamp)
        if opposite_time and opposite_time > last_same_time:
            return True, (
                f"Opposite-side signal ({last_opposite_side.side}) "
                f"at {opposite_time.isoformat()} resets cooldown"
            )

    elapsed_minutes = (now_ts - last_same_time).total_seconds() / 60.0
    min_interval = max(config.min_interval_minutes or 0.0, 0.0)
    cooldown_required = min_interval > 0
    cooldown_met = not cooldown_required or elapsed_minutes >= min_interval

    last_price = last_same_side.price
    if last_price and last_price > 0:
        price_change_pct = abs((current_price - last_price) / last_price * 100)
    else:
        price_change_pct = None
    min_pct = max(config.min_price_change_pct or 0.0, 0.0)
    price_required = min_pct > 0
    price_met = not price_required or (
        price_change_pct is not None and price_change_pct >= min_pct
    )

    if not cooldown_met and cooldown_required:
        return (
            False,
            f"THROTTLED_MIN_TIME (elapsed {elapsed_minutes:.2f}m < {min_interval:.2f}m)",
        )
    if not price_met and price_required:
        direction = "↑" if (last_price and current_price > last_price) else "↓" if last_price else ""
        return (
            False,
            f"THROTTLED_MIN_CHANGE (absolute price change {direction} {(price_change_pct or 0.0):.2f}% < {min_pct:.2f}%)",
        )

    summary_parts = []
    if cooldown_required:
        summary_parts.append(f"Δt={elapsed_minutes:.2f}m>= {min_interval:.2f}m")
    if price_required and price_change_pct is not None:
        direction = "↑" if (last_price and current_price > last_price) else "↓" if last_price else ""
        summary_parts.append(f"|Δp|={direction} {price_change_pct:.2f}%>= {min_pct:.2f}%")
    reason = " & ".join(summary_parts) if summary_parts else "No previous limits configured"
    return True, reason


def record_signal_event(
    db: Session,
    *,
    symbol: str,
    strategy_key: str,
    side: str,
    price: Optional[float],
    source: str,
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
            existing.last_price = price
            existing.last_time = now_ts
            existing.last_source = source
        else:
            db.add(
                SignalThrottleState(
                    symbol=symbol,
                    strategy_key=strategy_key,
                    side=side,
                    last_price=price,
                    last_time=now_ts,
                    last_source=source,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
