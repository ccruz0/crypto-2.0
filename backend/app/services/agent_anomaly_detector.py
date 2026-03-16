"""
Anomaly detection layer for the Automated Trading Platform.

Detection-only: inspects local/project data, creates Notion tasks for
discovered anomalies, logs activity events, and optionally sends Telegram
notifications.  Never modifies trading execution, exchange sync, deployment,
infrastructure, nginx, docker, or runtime config.

Reuses:
- notion_tasks.create_notion_task  (task creation with dedup)
- agent_activity_log.log_agent_event  (structured JSONL activity log)
- telegram_notifier.telegram_notifier.send_message  (safe Telegram notifier)
- database / ORM models  (ExchangeOrder, TradeSignal)
- agent_activity_log.get_recent_agent_events  (scheduler inactivity check)

Alert suppression: Telegram alerts for the same anomaly type are throttled
(ANOMALY_ALERT_COOLDOWN_HOURS) to prevent spam when an incident remains
unresolved. Cooldown resets when the anomaly clears (detector returns None).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Throttle Telegram alerts for same anomaly type (prevents spam on unresolved incidents)
_ANOMALY_ALERT_LAST_SENT: dict[str, datetime] = {}
_DEFAULT_COOLDOWN_HOURS = 24


def _get_anomaly_cooldown_hours() -> int:
    """Read ANOMALY_ALERT_COOLDOWN_HOURS from env (default 24)."""
    raw = (os.environ.get("ANOMALY_ALERT_COOLDOWN_HOURS") or "").strip()
    if raw:
        try:
            return max(1, min(168, int(raw)))  # 1h to 7 days
        except ValueError:
            pass
    return _DEFAULT_COOLDOWN_HOURS


def _should_send_anomaly_telegram(anomaly_type: str) -> bool:
    """
    True if we should send a Telegram alert for this anomaly type.
    Throttles repeated alerts for the same unresolved incident.
    Cooldown resets when anomaly clears (call _clear_anomaly_incident when detector returns None).
    """
    now = _utc_now()
    last_sent = _ANOMALY_ALERT_LAST_SENT.get(anomaly_type)
    cooldown_hours = _get_anomaly_cooldown_hours()
    if last_sent is None:
        return True
    if now - last_sent >= timedelta(hours=cooldown_hours):
        return True
    return False


def _record_anomaly_alert_sent(anomaly_type: str) -> None:
    """Record that we sent a Telegram alert for this anomaly type."""
    _ANOMALY_ALERT_LAST_SENT[anomaly_type] = _utc_now()


def _clear_anomaly_incident(anomaly_type: str) -> None:
    """Call when anomaly clears (detector returns None). Resets so next detection alerts immediately."""
    _ANOMALY_ALERT_LAST_SENT.pop(anomaly_type, None)

ANOMALY_SOURCE = "monitoring"
ANOMALY_STATUS = "planned"
ANOMALY_PROJECT = "Operations"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _log_event(event_type: str, *, details: dict[str, Any] | None = None) -> None:
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(event_type, details=details or {})
    except Exception as e:
        logger.debug("agent_anomaly_detector: log_agent_event failed (non-fatal) %s", e)


def _notify_telegram(message: str) -> bool:
    try:
        from app.services.telegram_notifier import telegram_notifier
        return telegram_notifier.send_message(message, chat_destination="ops")
    except Exception as e:
        logger.debug("agent_anomaly_detector: telegram notification failed (non-fatal) %s", e)
        return False


def _create_anomaly_task(
    title: str,
    anomaly_type: str,
    details: str,
    priority: Optional[str] = None,
) -> dict[str, Any] | None:
    """Create a Notion task for a detected anomaly and log the event."""
    try:
        from app.services.notion_tasks import create_notion_task
        result = create_notion_task(
            title=title,
            project=ANOMALY_PROJECT,
            type=anomaly_type,
            priority=priority,
            details=details,
            status=ANOMALY_STATUS,
            source=ANOMALY_SOURCE,
        )
        if result:
            _log_event("anomaly_task_created", details={
                "notion_page_id": result.get("id", ""),
                "title": title,
                "anomaly_type": anomaly_type,
            })
        return result
    except Exception as e:
        logger.warning("agent_anomaly_detector: create_notion_task failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Detector A: Open order mismatch
# ---------------------------------------------------------------------------

def detect_open_order_mismatch() -> dict[str, Any] | None:
    """
    Compare exchange open-order count (from DB rows with active statuses)
    against the cached unified open-orders snapshot.

    Returns structured metadata if a mismatch is found, None otherwise.
    """
    try:
        from app.database import SessionLocal
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
    except Exception as e:
        logger.debug("detect_open_order_mismatch: import failed %s", e)
        return None

    active_statuses = (
        OrderStatusEnum.NEW,
        OrderStatusEnum.ACTIVE,
        OrderStatusEnum.PARTIALLY_FILLED,
    )

    db_count: int = 0
    db_symbols: list[str] = []
    try:
        db = SessionLocal()
        try:
            rows = (
                db.query(ExchangeOrder)
                .filter(ExchangeOrder.status.in_(active_statuses))
                .all()
            )
            db_count = len(rows)
            db_symbols = sorted({str(r.symbol) for r in rows})
        finally:
            db.close()
    except Exception as e:
        logger.debug("detect_open_order_mismatch: db query failed %s", e)
        return None

    cache_count: int | None = None
    cache_symbols: list[str] = []
    try:
        from app.services.open_orders_cache import get_unified_open_orders
        cached_orders, _cached_ts = get_unified_open_orders()
        if cached_orders is not None:
            cache_count = len(cached_orders)
            cache_symbols = sorted(
                {getattr(o, "symbol", str(o)) for o in cached_orders} if cached_orders else set()
            )
    except Exception:
        pass

    if cache_count is None:
        return None

    if db_count == cache_count:
        return None

    diff = abs(db_count - cache_count)
    return {
        "anomaly": "open_order_mismatch",
        "db_open_count": db_count,
        "cache_open_count": cache_count,
        "difference": diff,
        "db_symbols": db_symbols,
        "cache_symbols": cache_symbols,
        "detected_at": _utc_now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Detector B: Signal quality degradation
# ---------------------------------------------------------------------------

_SIGNAL_LOOKBACK_DAYS = 7
_SIGNAL_MIN_SAMPLE = 5
_DEGRADATION_THRESHOLD = 0.25  # success rate drop considered material


def detect_signal_quality_degradation() -> dict[str, Any] | None:
    """
    Simple heuristic: compare recent signal fill-rate against a longer
    historical baseline.  If recent success rate drops materially below
    baseline, flag as degradation.

    Returns structured metadata if degradation is found, None otherwise.
    """
    try:
        from app.database import SessionLocal
        from app.models.trade_signal import TradeSignal, SignalStatusEnum
    except Exception as e:
        logger.debug("detect_signal_quality_degradation: import failed %s", e)
        return None

    now = _utc_now()
    recent_cutoff = now - timedelta(days=_SIGNAL_LOOKBACK_DAYS)
    baseline_cutoff = now - timedelta(days=_SIGNAL_LOOKBACK_DAYS * 4)

    try:
        db = SessionLocal()
        try:
            all_signals = (
                db.query(TradeSignal)
                .filter(TradeSignal.created_at >= baseline_cutoff)
                .all()
            )
        finally:
            db.close()
    except Exception as e:
        logger.debug("detect_signal_quality_degradation: db query failed %s", e)
        return None

    if not all_signals:
        return None

    filled_statuses = {SignalStatusEnum.FILLED, SignalStatusEnum.CLOSED}

    recent = [s for s in all_signals if s.created_at and s.created_at >= recent_cutoff]
    baseline = [s for s in all_signals if s.created_at and s.created_at < recent_cutoff]

    if len(recent) < _SIGNAL_MIN_SAMPLE or len(baseline) < _SIGNAL_MIN_SAMPLE:
        return None

    recent_success = sum(1 for s in recent if s.status in filled_statuses)
    baseline_success = sum(1 for s in baseline if s.status in filled_statuses)

    recent_rate = recent_success / len(recent)
    baseline_rate = baseline_success / len(baseline)

    if baseline_rate <= 0:
        return None

    drop = baseline_rate - recent_rate
    if drop < _DEGRADATION_THRESHOLD:
        return None

    return {
        "anomaly": "signal_quality_degradation",
        "recent_period_days": _SIGNAL_LOOKBACK_DAYS,
        "baseline_period_days": _SIGNAL_LOOKBACK_DAYS * 4,
        "recent_count": len(recent),
        "recent_success_rate": round(recent_rate, 4),
        "baseline_count": len(baseline),
        "baseline_success_rate": round(baseline_rate, 4),
        "rate_drop": round(drop, 4),
        "threshold": _DEGRADATION_THRESHOLD,
        "detected_at": _utc_now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Detector C: Scheduler inactivity
# ---------------------------------------------------------------------------

_SCHEDULER_EXPECTED_INTERVAL_MINUTES = 15


def detect_scheduler_inactivity() -> dict[str, Any] | None:
    """
    Check agent activity log for recent scheduler_cycle_started events.
    If none found within the expected interval, flag as inactivity.

    Returns structured metadata if inactivity is detected, None otherwise.
    """
    try:
        from app.services.agent_activity_log import get_recent_agent_events
    except Exception as e:
        logger.debug("detect_scheduler_inactivity: import failed %s", e)
        return None

    events = get_recent_agent_events(limit=100)
    if not events:
        return {
            "anomaly": "scheduler_inactivity",
            "reason": "no activity events found at all",
            "expected_interval_minutes": _SCHEDULER_EXPECTED_INTERVAL_MINUTES,
            "last_cycle_at": None,
            "detected_at": _utc_now().isoformat(),
        }

    scheduler_events = [
        e for e in events
        if (e.get("event_type") or "") in (
            "scheduler_cycle_started",
            "scheduler_auto_executed",
            "scheduler_approval_requested",
        )
    ]

    if not scheduler_events:
        return {
            "anomaly": "scheduler_inactivity",
            "reason": "no scheduler cycle events in recent activity log",
            "expected_interval_minutes": _SCHEDULER_EXPECTED_INTERVAL_MINUTES,
            "last_cycle_at": None,
            "detected_at": _utc_now().isoformat(),
        }

    latest_ts_str = scheduler_events[0].get("timestamp", "")
    try:
        latest_ts = datetime.fromisoformat(latest_ts_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None

    now = _utc_now()
    gap = now - latest_ts
    if gap <= timedelta(minutes=_SCHEDULER_EXPECTED_INTERVAL_MINUTES):
        return None

    return {
        "anomaly": "scheduler_inactivity",
        "reason": "scheduler cycle not seen within expected interval",
        "expected_interval_minutes": _SCHEDULER_EXPECTED_INTERVAL_MINUTES,
        "gap_minutes": round(gap.total_seconds() / 60, 1),
        "last_cycle_at": latest_ts_str,
        "detected_at": _utc_now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Main cycle
# ---------------------------------------------------------------------------

_DETECTOR_REGISTRY: list[tuple[str, Any]] = [
    ("open_order_mismatch", detect_open_order_mismatch),
    ("signal_quality_degradation", detect_signal_quality_degradation),
    ("scheduler_inactivity", detect_scheduler_inactivity),
]


def _build_task_title(anomaly: dict[str, Any]) -> str:
    name = (anomaly.get("anomaly") or "unknown").replace("_", " ").title()
    return f"[Anomaly] {name}"


def _build_task_details(anomaly: dict[str, Any]) -> str:
    lines = [f"Anomaly type: {anomaly.get('anomaly', 'unknown')}"]
    for k, v in anomaly.items():
        if k in ("anomaly",):
            continue
        lines.append(f"{k}: {v}")
    return "\n".join(lines)


def _anomaly_type_to_notion_type(anomaly_name: str) -> str:
    mapping = {
        "open_order_mismatch": "monitoring",
        "signal_quality_degradation": "strategy",
        "scheduler_inactivity": "monitoring",
    }
    return mapping.get(anomaly_name, "monitoring")


def run_anomaly_detection_cycle() -> dict[str, Any]:
    """
    Run all registered anomaly detectors.  For each anomaly found:
    - create a Notion task
    - log an activity event
    - optionally send a Telegram notification

    Returns a summary dict with anomalies found and tasks created.
    """
    logger.info("anomaly_detection_cycle_start ts=%s", _utc_now().isoformat())
    _log_event("anomaly_detection_cycle_started")

    anomalies_found: list[dict[str, Any]] = []
    tasks_created: list[dict[str, Any]] = []
    errors: list[str] = []

    for detector_name, detector_fn in _DETECTOR_REGISTRY:
        try:
            result = detector_fn()
            if result is None:
                _clear_anomaly_incident(detector_name)
                continue

            anomaly_type = result.get("anomaly", detector_name)
            anomalies_found.append(result)
            _log_event("anomaly_detected", details={
                "detector": detector_name,
                "anomaly": anomaly_type,
            })

            title = _build_task_title(result)
            details = _build_task_details(result)
            notion_type = _anomaly_type_to_notion_type(anomaly_type)

            task = _create_anomaly_task(
                title=title,
                anomaly_type=notion_type,
                details=details,
            )
            if task:
                tasks_created.append({
                    "notion_page_id": task.get("id", ""),
                    "title": title,
                    "anomaly": anomaly_type,
                })

            if _should_send_anomaly_telegram(anomaly_type):
                _notify_telegram(
                    f"🔍 <b>Anomaly detected</b>: {title}\n"
                    f"Type: {anomaly_type}\n"
                    f"Details: {details[:300]}"
                )
                _record_anomaly_alert_sent(anomaly_type)
            else:
                logger.debug(
                    "anomaly_detection: throttled Telegram for %s (cooldown active)",
                    anomaly_type,
                )
        except Exception as e:
            logger.warning("anomaly_detection: detector %s failed: %s", detector_name, e)
            errors.append(f"{detector_name}: {e}")

    _log_event("anomaly_detection_cycle_completed", details={
        "anomalies_found": len(anomalies_found),
        "tasks_created": len(tasks_created),
        "errors": len(errors),
    })

    summary = {
        "ok": True,
        "anomalies_found": len(anomalies_found),
        "tasks_created": len(tasks_created),
        "anomalies": anomalies_found,
        "tasks": tasks_created,
        "errors": errors,
        "completed_at": _utc_now().isoformat(),
    }

    logger.info(
        "anomaly_detection_cycle_done anomalies=%d tasks=%d errors=%d",
        len(anomalies_found),
        len(tasks_created),
        len(errors),
    )
    return summary
