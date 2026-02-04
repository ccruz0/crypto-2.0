"""Central alert emission helper
Provides a single entry point for all alert emissions with standardized logging.
"""
import logging
import uuid
from typing import Literal, Optional, Dict, Any
from app.services.telegram_notifier import telegram_notifier
from app.core.runtime import get_runtime_origin
from app.core.config import settings

logger = logging.getLogger(__name__)


def emit_alert(
    symbol: str,
    side: Literal["BUY", "SELL"],
    reason: str,
    price: float,
    context: Optional[Dict[str, Any]] = None,
    dry_run: Optional[bool] = None,
    strategy_type: Optional[str] = None,
    risk_approach: Optional[str] = None,
    price_variation: Optional[str] = None,
    throttle_status: Optional[str] = None,
    throttle_reason: Optional[str] = None,
    db: Optional[Any] = None,
    **kwargs: Any,
) -> bool:
    """
    Central function to emit an alert from the monitor.

    - Logs the decision with [ALERT_DECISION]
    - Optionally skips sending if dry_run is True (logs [ALERT_SKIP])
    - Persists in DB via telegram_notifier
    - Sends Telegram message
    - Logs success with [ALERT_ENQUEUED]

    Args:
        symbol: Trading symbol (e.g., "BTC_USDT")
        side: "BUY" or "SELL"
        reason: Human-readable reason for the alert
        price: Current price
        context: Optional context dict with preset, risk, decision_index, etc.
        dry_run: If True, log but don't send. If None, uses settings.ALERTS_DRY_RUN
        strategy_type: Strategy type (e.g., "Swing", "Intraday")
        risk_approach: Risk approach (e.g., "Conservative", "Aggressive")
        price_variation: Optional price variation text
        throttle_status: Optional throttle status
        throttle_reason: Optional throttle reason

    Returns:
        True if alert was sent successfully, False otherwise
    """
    # Resolve dry_run from settings if not provided
    if dry_run is None:
        dry_run = getattr(settings, "ALERTS_DRY_RUN", False)

    # Get runtime origin
    origin = get_runtime_origin()

    # Correlation ID: from kwargs/context or evaluation_id (signal_monitor) or generate once per alert
    correlation_id = (
        kwargs.get("correlation_id")
        or (context or {}).get("correlation_id")
        or kwargs.get("evaluation_id")
    )
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    # Log the decision (include correlation_id for traceability)
    logger.info(
        "[ALERT_DECISION] symbol=%s side=%s reason=%s dry_run=%s origin=%s correlation_id=%s context=%s",
        symbol,
        side,
        reason,
        dry_run,
        origin,
        correlation_id,
        context or {},
    )

    # Dry run: persist to DB only (no Telegram send, no order) for regression proof
    if dry_run:
        logger.info(
            "[ALERT_SKIP] symbol=%s side=%s reason=%s (dry run, persisting to DB only) correlation_id=%s",
            symbol,
            side,
            reason,
            correlation_id,
        )
        try:
            if side == "BUY":
                result = telegram_notifier.send_buy_signal(
                    symbol=symbol,
                    price=price,
                    reason=reason,
                    strategy_type=strategy_type,
                    risk_approach=risk_approach,
                    price_variation=price_variation,
                    source="LIVE ALERT",
                    throttle_status=throttle_status or "SENT",
                    throttle_reason=throttle_reason,
                    origin=origin,
                    db=db,
                    persist_only=True,
                    correlation_id=correlation_id,
                )
            else:
                result = telegram_notifier.send_sell_signal(
                    symbol=symbol,
                    price=price,
                    reason=reason,
                    strategy_type=strategy_type,
                    risk_approach=risk_approach,
                    price_variation=price_variation,
                    source="LIVE ALERT",
                    throttle_status=throttle_status or "SENT",
                    throttle_reason=throttle_reason,
                    origin=origin,
                    db=db,
                    persist_only=True,
                    correlation_id=correlation_id,
                )
            logger.info(
                "[ALERT_ENQUEUED] symbol=%s side=%s dry_run=True persisted=%s correlation_id=%s",
                symbol,
                side,
                result,
                correlation_id,
            )
            return result
        except Exception as e:
            logger.error(
                "[ALERT_ENQUEUED] symbol=%s side=%s dry_run=True persisted=False error=%s correlation_id=%s",
                symbol,
                side,
                str(e),
                correlation_id,
                exc_info=True,
            )
            return False

    # Emit the alert via telegram_notifier (pass db so add_telegram_message persists in same transaction)
    try:
        if side == "BUY":
            result = telegram_notifier.send_buy_signal(
                symbol=symbol,
                price=price,
                reason=reason,
                strategy_type=strategy_type,
                risk_approach=risk_approach,
                price_variation=price_variation,
                source="LIVE ALERT",
                throttle_status=throttle_status,
                throttle_reason=throttle_reason,
                origin=origin,
                db=db,
                correlation_id=correlation_id,
            )
        else:  # SELL
            result = telegram_notifier.send_sell_signal(
                symbol=symbol,
                price=price,
                reason=reason,
                strategy_type=strategy_type,
                risk_approach=risk_approach,
                price_variation=price_variation,
                source="LIVE ALERT",
                throttle_status=throttle_status,
                throttle_reason=throttle_reason,
                origin=origin,
                db=db,
                correlation_id=correlation_id,
            )

        # Log enqueued status
        logger.info(
            "[ALERT_ENQUEUED] symbol=%s side=%s reason=%s sent=%s origin=%s",
            symbol,
            side,
            reason,
            result,
            origin,
        )

        return result

    except Exception as e:
        logger.error(
            "[ALERT_ENQUEUED] symbol=%s side=%s reason=%s sent=False error=%s",
            symbol,
            side,
            reason,
            str(e),
            exc_info=True,
        )
        return False

