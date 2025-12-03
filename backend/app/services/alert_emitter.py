"""Central alert emission helper
Provides a single entry point for all alert emissions with standardized logging.
"""
import logging
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

    # Log the decision
    logger.info(
        "[ALERT_DECISION] symbol=%s side=%s reason=%s dry_run=%s origin=%s context=%s",
        symbol,
        side,
        reason,
        dry_run,
        origin,
        context or {},
    )

    # Skip if dry run
    if dry_run:
        logger.info(
            "[ALERT_SKIP] symbol=%s side=%s reason=%s (dry run, not sent)",
            symbol,
            side,
            reason,
        )
        return False

    # Emit the alert via telegram_notifier
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

