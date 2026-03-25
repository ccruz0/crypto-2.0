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
unresolved. Uses DB (TradingSettings) so all backend instances share cooldown
state. Cooldown resets when the anomaly clears (detector returns None).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Throttle Telegram alerts for same anomaly type (prevents spam on unresolved incidents).
# Uses DB (TradingSettings) so all backend instances share cooldown state.
_DEFAULT_COOLDOWN_HOURS = 24
_ANOMALY_ALERT_KEY_PREFIX = "anomaly_alert_last_sent_"


def _get_anomaly_cooldown_hours() -> int:
    """Read ANOMALY_ALERT_COOLDOWN_HOURS from env (default 24)."""
    raw = (os.environ.get("ANOMALY_ALERT_COOLDOWN_HOURS") or "").strip()
    if raw:
        try:
            return max(1, min(168, int(raw)))  # 1h to 7 days
        except ValueError:
            pass
    return _DEFAULT_COOLDOWN_HOURS


def _anomaly_alert_key(anomaly_type: str) -> str:
    return f"{_ANOMALY_ALERT_KEY_PREFIX}{anomaly_type}"


def _get_anomaly_alert_last_sent_db(anomaly_type: str) -> datetime | None:
    """Read last-sent timestamp from DB. Returns None if not found or on error."""
    try:
        from app.database import SessionLocal
        from app.models.trading_settings import TradingSettings
    except Exception:
        return None
    db = SessionLocal()
    try:
        key = _anomaly_alert_key(anomaly_type)
        row = db.query(TradingSettings).filter(TradingSettings.setting_key == key).first()
        if not row or not row.setting_value:
            return None
        return datetime.fromisoformat(row.setting_value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    except Exception as e:
        logger.debug("agent_anomaly_detector: _get_anomaly_alert_last_sent_db failed: %s", e)
        return None
    finally:
        db.close()


def _set_anomaly_alert_last_sent_db(anomaly_type: str, ts: datetime) -> None:
    """Write last-sent timestamp to DB."""
    try:
        from app.database import SessionLocal
        from app.models.trading_settings import TradingSettings
    except Exception:
        return
    db = SessionLocal()
    try:
        key = _anomaly_alert_key(anomaly_type)
        value = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        row = db.query(TradingSettings).filter(TradingSettings.setting_key == key).first()
        if row:
            row.setting_value = value
        else:
            db.add(TradingSettings(setting_key=key, setting_value=value))
        db.commit()
    except Exception as e:
        logger.debug("agent_anomaly_detector: _set_anomaly_alert_last_sent_db failed: %s", e)
        db.rollback()
    finally:
        db.close()


def _clear_anomaly_alert_sent_db(anomaly_type: str) -> None:
    """Remove last-sent record from DB (when anomaly clears)."""
    try:
        from app.database import SessionLocal
        from app.models.trading_settings import TradingSettings
    except Exception:
        return
    db = SessionLocal()
    try:
        key = _anomaly_alert_key(anomaly_type)
        row = db.query(TradingSettings).filter(TradingSettings.setting_key == key).first()
        if row:
            db.delete(row)
            db.commit()
    except Exception as e:
        logger.debug("agent_anomaly_detector: _clear_anomaly_alert_sent_db failed: %s", e)
        db.rollback()
    finally:
        db.close()


def _should_send_anomaly_telegram(anomaly_type: str) -> bool:
    """
    True if we should send a Telegram alert for this anomaly type.
    Uses DB so all backend instances share cooldown state.

    For scheduler_inactivity: one alert per incident (send only if never sent for this
    incident; cooldown resets when anomaly clears, not by time).
    """
    last_sent = _get_anomaly_alert_last_sent_db(anomaly_type)
    if anomaly_type == "scheduler_inactivity":
        return last_sent is None
    now = _utc_now()
    cooldown_hours = _get_anomaly_cooldown_hours()
    if last_sent is None:
        return True
    if now - last_sent >= timedelta(hours=cooldown_hours):
        return True
    return False


def _record_anomaly_alert_sent(anomaly_type: str) -> None:
    """Record that we sent a Telegram alert for this anomaly type (persists to DB)."""
    _set_anomaly_alert_last_sent_db(anomaly_type, _utc_now())


def _clear_anomaly_incident(anomaly_type: str) -> None:
    """Call when anomaly clears (detector returns None). Resets so next detection alerts immediately."""
    _clear_anomaly_alert_sent_db(anomaly_type)

ANOMALY_SOURCE = "monitoring"
ANOMALY_STATUS = "planned"
ANOMALY_PROJECT = "Operations"
_ANOMALY_TASK_DEDUP_WINDOW_MINUTES_DEFAULT = 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _anomaly_task_dedup_window_minutes() -> int:
    """Read anomaly task dedup window from env; default 60 minutes."""
    raw = (os.environ.get("ANOMALY_TASK_DEDUP_WINDOW_MINUTES") or "").strip()
    if raw:
        try:
            # Keep within requested operational range (30-60) by default,
            # but allow up to 24h for emergency tuning.
            return max(30, min(1440, int(raw)))
        except ValueError:
            pass
    return _ANOMALY_TASK_DEDUP_WINDOW_MINUTES_DEFAULT


def _parse_iso_ts(value: str) -> datetime | None:
    v = (value or "").strip()
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _find_active_anomaly_task(anomaly_name: str) -> dict[str, Any] | None:
    """
    Return an active anomaly task for the same anomaly type within dedup window.

    Active statuses: Planned, In Progress, Ready for Investigation, Patching.
    """
    try:
        from app.services.notion_task_reader import get_tasks_by_status
    except Exception as e:
        logger.debug("agent_anomaly_detector: get_tasks_by_status import failed: %s", e)
        return None

    statuses = ["planned", "in-progress", "ready-for-investigation", "patching"]
    tasks = get_tasks_by_status(statuses, max_results=200)
    if not tasks:
        return None

    needle = f"anomaly type: {anomaly_name}".lower()
    now = _utc_now()
    window = timedelta(minutes=_anomaly_task_dedup_window_minutes())

    for task in tasks:
        details = str(task.get("details") or "")
        if needle not in details.lower():
            continue
        ts = _parse_iso_ts(str(task.get("last_edited_time") or "")) or _parse_iso_ts(str(task.get("created_time") or ""))
        if ts is not None and now - ts > window:
            continue
        return task
    return None


def _extract_anomaly_type_from_details(details: str) -> str:
    """Extract anomaly type marker from task details."""
    for line in (details or "").splitlines():
        s = line.strip()
        if s.lower().startswith("anomaly type:"):
            return s.split(":", 1)[1].strip().lower()
    return ""


def _status_rank_for_cleanup(status: str) -> int:
    # Higher rank = further along in active lifecycle.
    s = (status or "").strip().lower()
    if s == "patching":
        return 4
    if s == "in-progress":
        return 3
    if s == "ready-for-investigation":
        return 2
    if s == "planned":
        return 1
    return 0


def _cleanup_duplicate_anomaly_tasks() -> int:
    """
    Close duplicate active anomaly tasks, keeping one canonical task per anomaly type.

    Rule:
    - Only tasks with explicit details marker "Anomaly type: <type>" are considered.
    - Active statuses scanned: planned, in-progress, ready-for-investigation, patching.
    - Keep canonical task by (furthest status rank, newest timestamp).
    - Close others as rejected with a dedup comment referencing kept task id.
    """
    try:
        from app.services.notion_task_reader import get_tasks_by_status
        from app.services.notion_tasks import update_notion_task_status
    except Exception as e:
        logger.debug("agent_anomaly_detector: duplicate cleanup imports failed: %s", e)
        return 0

    statuses = ["planned", "in-progress", "ready-for-investigation", "patching"]
    tasks = get_tasks_by_status(statuses, max_results=500)
    if not tasks:
        return 0

    grouped: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        anomaly_name = _extract_anomaly_type_from_details(str(task.get("details") or ""))
        if not anomaly_name:
            continue  # never touch non-anomaly tasks
        grouped.setdefault(anomaly_name, []).append(task)

    closed_count = 0
    for anomaly_name, same_type_tasks in grouped.items():
        if len(same_type_tasks) <= 1:
            continue

        def _sort_key(t: dict[str, Any]) -> tuple[int, float]:
            status_rank = _status_rank_for_cleanup(str(t.get("status") or ""))
            ts = _parse_iso_ts(str(t.get("last_edited_time") or "")) or _parse_iso_ts(str(t.get("created_time") or ""))
            ts_epoch = ts.timestamp() if ts else 0.0
            return status_rank, ts_epoch

        ordered = sorted(same_type_tasks, key=_sort_key, reverse=True)
        keep = ordered[0]
        keep_id = str(keep.get("id") or "")

        for dup in ordered[1:]:
            dup_id = str(dup.get("id") or "")
            if not dup_id:
                continue
            comment = "Closed as duplicate during anomaly dedup cleanup"
            if keep_id:
                comment += f" (kept task: {keep_id})"
            ok = update_notion_task_status(dup_id, "rejected", append_comment=comment)
            if ok:
                closed_count += 1
                logger.info(
                    "anomaly_duplicate_cleanup_closed anomaly=%s closed_task_id=%s kept_task_id=%s",
                    anomaly_name,
                    dup_id[:12],
                    keep_id[:12],
                )
                _log_event("anomaly_duplicate_cleanup_closed", details={
                    "anomaly_type": anomaly_name,
                    "closed_task_id": dup_id,
                    "kept_task_id": keep_id,
                })

    return closed_count


def _log_event(event_type: str, *, details: dict[str, Any] | None = None) -> None:
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(event_type, details=details or {})
    except Exception as e:
        logger.debug("agent_anomaly_detector: log_agent_event failed (non-fatal) %s", e)


def _notify_telegram(message: str) -> bool:
    """Send to Claw (task-system). Anomaly detector creates Notion tasks. Suppressed in quiet mode."""
    try:
        from app.services.agent_telegram_policy import is_quiet_mode
        if is_quiet_mode():
            logger.debug("agent_anomaly_detector: telegram notification suppressed (quiet mode)")
            return False
    except Exception:
        pass
    try:
        from app.services.claw_telegram import send_claw_message
        sent, _ = send_claw_message(message, message_type="TASK", source_module="agent_anomaly_detector")
        return sent
    except Exception as e:
        logger.debug("agent_anomaly_detector: telegram notification failed (non-fatal) %s", e)
        return False


def _create_anomaly_task(
    title: str,
    anomaly_name: str,
    anomaly_type: str,
    details: str,
    priority: Optional[str] = None,
) -> dict[str, Any] | None:
    """Create a Notion task for a detected anomaly and log the event."""
    existing = _find_active_anomaly_task(anomaly_name)
    if existing:
        existing_id = str(existing.get("id") or "")
        logger.info(
            "anomaly_task_deduplicated anomaly=%s existing_task_id=%s title=%r",
            anomaly_name,
            existing_id[:12],
            str(existing.get("task") or "")[:120],
        )
        _log_event("anomaly_task_deduplicated", details={
            "anomaly_type": anomaly_name,
            "existing_task_id": existing_id,
            "existing_status": str(existing.get("status") or ""),
        })
        return None

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


def _scheduler_inactivity_threshold_minutes() -> int:
    """
    Compute inactivity threshold from scheduler interval.

    Uses max(15, 3x interval) to avoid false positives when cycles are busy/noisy.
    """
    try:
        from app.services.agent_scheduler import _get_scheduler_interval

        interval_sec = int(_get_scheduler_interval())
        return max(_SCHEDULER_EXPECTED_INTERVAL_MINUTES, int((interval_sec * 3) / 60))
    except Exception:
        return _SCHEDULER_EXPECTED_INTERVAL_MINUTES


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

    # Large window: high-volume logs can push heartbeat events out of small tails.
    events = get_recent_agent_events(limit=2000)
    expected_interval_minutes = _scheduler_inactivity_threshold_minutes()
    if not events:
        return {
            "anomaly": "scheduler_inactivity",
            "reason": "no activity events found at all",
            "expected_interval_minutes": expected_interval_minutes,
            "last_cycle_at": None,
            "detected_at": _utc_now().isoformat(),
        }

    # Any of these count as "scheduler ran recently" (heartbeat)
    _SCHEDULER_HEARTBEAT_EVENTS = (
        "scheduler_cycle_started",
        "scheduler_cycle_completed",
        "scheduler_heartbeat_updated",
        "scheduler_auto_executed",
        "scheduler_approval_requested",
    )
    scheduler_events = [
        e for e in events
        if (e.get("event_type") or "") in _SCHEDULER_HEARTBEAT_EVENTS
    ]

    if not scheduler_events:
        return {
            "anomaly": "scheduler_inactivity",
            "reason": "no scheduler cycle events in recent activity log",
            "expected_interval_minutes": expected_interval_minutes,
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
    if gap <= timedelta(minutes=expected_interval_minutes):
        return None

    return {
        "anomaly": "scheduler_inactivity",
        "reason": "scheduler cycle not seen within expected interval",
        "expected_interval_minutes": expected_interval_minutes,
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
    try:
        closed = _cleanup_duplicate_anomaly_tasks()
        if closed:
            logger.info("anomaly_duplicate_cleanup_done closed=%d", closed)
    except Exception as e:
        logger.warning("anomaly_duplicate_cleanup failed: %s", e)

    anomalies_found: list[dict[str, Any]] = []
    tasks_created: list[dict[str, Any]] = []
    errors: list[str] = []

    for detector_name, detector_fn in _DETECTOR_REGISTRY:
        try:
            result = detector_fn()
            if result is None:
                if detector_name == "scheduler_inactivity":
                    last_sent = _get_anomaly_alert_last_sent_db("scheduler_inactivity")
                    if last_sent is not None:
                        _notify_telegram(
                            "✅ <b>Scheduler recovered</b>\n"
                            "Scheduler inactivity anomaly cleared; cycles are running again."
                        )
                        _log_event("scheduler_recovered", details={})
                    _clear_anomaly_incident(detector_name)
                else:
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

            # Scheduler inactivity: one task+alert per incident; no resend until recovered.
            # (Previously only Telegram was deduped; Notion tasks were still recreated each cycle.)
            if anomaly_type == "scheduler_inactivity":
                should_emit_incident = _should_send_anomaly_telegram(anomaly_type)
                if should_emit_incident:
                    notion_type = _anomaly_type_to_notion_type(anomaly_type)
                    task = _create_anomaly_task(
                        title=title,
                        anomaly_name=anomaly_type,
                        anomaly_type=notion_type,
                        details=details,
                    )
                    if task:
                        tasks_created.append({
                            "notion_page_id": task.get("id", ""),
                            "title": title,
                            "anomaly": anomaly_type,
                        })
                    _notify_telegram(
                        f"🔍 <b>Anomaly detected</b>: {title}\n"
                        f"Type: {anomaly_type}\n"
                        f"Details: {details[:300]}"
                    )
                    _record_anomaly_alert_sent(anomaly_type)
                else:
                    logger.info(
                        "scheduler_inactivity_incident_suppressed (task+alert already sent; will emit again when scheduler recovers)"
                    )
                    _log_event("scheduler_inactivity_alert_suppressed", details={"anomaly": anomaly_type})
            else:
                notion_type = _anomaly_type_to_notion_type(anomaly_type)
                task = _create_anomaly_task(
                    title=title,
                    anomaly_name=anomaly_type,
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
