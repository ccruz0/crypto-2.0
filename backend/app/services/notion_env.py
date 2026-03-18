"""
Notion integration env check and self-healing (inline repair from SSM).

Used by:
- Startup: validate NOTION_* and set notion_integration_degraded.
- Scheduler pre-flight: ensure NOTION_* present; if missing, try SSM repair and set os.environ.
- Health endpoint: /api/health/notion reports env_ok, last_pickup_status, last_error.

No secrets are logged or exposed.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# SSM path for LAB (same as scripts/aws/render_runtime_env.sh)
SSM_NOTION_API_KEY_LAB = "/automated-trading-platform/lab/notion/api_key"
NOTION_TASK_DB_DEFAULT = "eb90cfa139f94724a8b476315908510a"

# Debounce: max one degraded alert per 30 minutes
NOTION_DEGRADED_ALERT_COOLDOWN_MINUTES = 30

# Module-level state for health and startup
_notion_degraded: bool = False
_notion_env_source: str = "unknown"
_last_pickup_status: str = ""
_last_pickup_error: str = ""

# Persisted for transition detection and debounce (in-memory)
_last_health_ok: Optional[bool] = None
_last_degraded_alert_at: Optional[datetime] = None


def is_notion_integration_degraded() -> bool:
    """True if NOTION_* were missing at startup or last check and could not be repaired."""
    return _notion_degraded


def get_notion_env_source() -> str:
    """Source of NOTION_* (runtime.env, .env.aws, ssm_repair, unknown)."""
    return _notion_env_source


def check_notion_env() -> tuple[bool, str]:
    """
    Check if NOTION_API_KEY and NOTION_TASK_DB are present in env.
    Returns (ok: bool, source: str). Does not log secret values.
    """
    key = (os.environ.get("NOTION_API_KEY") or "").strip()
    db = (os.environ.get("NOTION_TASK_DB") or "").strip()
    if key and db:
        # Heuristic: if we just set from SSM it won't have a file source
        return True, _notion_env_source if _notion_env_source != "unknown" else "env"
    return False, "missing"


def try_repair_notion_env_from_ssm() -> bool:
    """
    Inline repair: fetch Notion API key from LAB SSM, set os.environ and optionally
    persist to .env.aws and secrets/runtime.env so next process/restart sees them.
    Returns True if env was repaired (NOTION_API_KEY and NOTION_TASK_DB now set).
    """
    global _notion_degraded, _notion_env_source
    try:
        import boto3
    except ImportError:
        logger.warning("notion_env: boto3 not available, cannot repair from SSM")
        return False

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-southeast-1"
    try:
        ssm = boto3.client("ssm", region_name=region)
        resp = ssm.get_parameter(Name=SSM_NOTION_API_KEY_LAB, WithDecryption=True)
        value = (resp.get("Parameter") or {}).get("Value") or ""
    except Exception as e:
        logger.warning("notion_env: SSM get_parameter failed name=%s error=%s", SSM_NOTION_API_KEY_LAB, e)
        return False

    if not (value or "").strip():
        return False

    api_key = value.strip()
    os.environ["NOTION_API_KEY"] = api_key
    if not (os.environ.get("NOTION_TASK_DB") or "").strip():
        os.environ["NOTION_TASK_DB"] = NOTION_TASK_DB_DEFAULT

    _notion_env_source = "ssm_repair"
    _notion_degraded = False
    logger.info(
        "notion_env auto_repair_triggered source=ssm_repair NOTION_API_KEY=present NOTION_TASK_DB=present"
    )

    # Persist so next restart sees them (best-effort)
    try:
        from app.services._paths import workspace_root
        root = workspace_root()
        env_aws = root / ".env.aws"
        runtime_env = root / "secrets" / "runtime.env"
        # .env.aws: upsert NOTION_* (replace existing lines or append)
        def _upsert_env_file(path: Path, key: str, val: str) -> None:
            if path.exists():
                lines = []
                found_key = False
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip().startswith(key + "="):
                        lines.append(f"{key}={val}")
                        found_key = True
                    else:
                        lines.append(line)
                if not found_key:
                    lines.append(f"{key}={val}")
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{key}={val}\n", encoding="utf-8")
        _upsert_env_file(env_aws, "NOTION_API_KEY", api_key)
        _upsert_env_file(env_aws, "NOTION_TASK_DB", NOTION_TASK_DB_DEFAULT)
        # runtime.env: append if not present
        runtime_env.parent.mkdir(parents=True, exist_ok=True)
        if runtime_env.exists():
            rcontent = runtime_env.read_text(encoding="utf-8")
            if "NOTION_API_KEY=" not in rcontent:
                rcontent = rcontent.rstrip() + "\nNOTION_API_KEY=" + api_key + "\nNOTION_TASK_DB=" + NOTION_TASK_DB_DEFAULT + "\n"
                runtime_env.write_text(rcontent, encoding="utf-8")
        else:
            runtime_env.write_text(
                "NOTION_API_KEY=" + api_key + "\nNOTION_TASK_DB=" + NOTION_TASK_DB_DEFAULT + "\n",
                encoding="utf-8",
            )
    except Exception as e:
        logger.debug("notion_env: persist to files failed (non-fatal): %s", e)

    return True


def validate_notion_env_at_startup() -> None:
    """
    Call at backend startup. Sets notion_integration_degraded if NOTION_* missing.
    Does not crash; only logs and sets state.
    """
    global _notion_degraded, _notion_env_source
    key = (os.environ.get("NOTION_API_KEY") or "").strip()
    db = (os.environ.get("NOTION_TASK_DB") or "").strip()
    if key and db:
        _notion_degraded = False
        _notion_env_source = "runtime.env"  # assume rendered
        logger.info(
            "notion_startup_validation NOTION_API_KEY=present NOTION_TASK_DB=present source=%s",
            _notion_env_source,
        )
        return
    _notion_degraded = True
    _notion_env_source = "missing"
    logger.warning(
        "notion_startup_validation NOTION_API_KEY=%s NOTION_TASK_DB=%s source=missing integration=degraded",
        "present" if key else "missing",
        "present" if db else "missing",
    )


def set_last_pickup_status(status: str, error: str = "") -> None:
    """Record last scheduler pickup result for health endpoint."""
    global _last_pickup_status, _last_pickup_error
    _last_pickup_status = (status or "")[:200]
    _last_pickup_error = (error or "")[:500]


def get_notion_health() -> dict[str, Any]:
    """Return dict for /api/health/notion: env_ok, last_pickup_status, last_error."""
    ok, source = check_notion_env()
    return {
        "env_ok": ok,
        "env_source": source,
        "degraded": _notion_degraded,
        "last_pickup_status": _last_pickup_status,
        "last_error": _last_pickup_error or None,
    }


def check_notion_health_transition_and_alert() -> None:
    """
    Compare current Notion health to previous state; log transition; send debounced
    Telegram alert when degraded (max 1 per 30 min) and one recovery alert when
    transitioning degraded → healthy. No secrets. Call from scheduler loop after each cycle.
    """
    global _last_health_ok, _last_degraded_alert_at

    health = get_notion_health()
    current_ok = bool(health.get("env_ok") and not health.get("degraded"))
    previous = _last_health_ok

    logger.info(
        "notion_health_transition previous=%s current=%s env_ok=%s degraded=%s",
        previous if previous is not None else "none",
        current_ok,
        health.get("env_ok"),
        health.get("degraded"),
    )
    _last_health_ok = current_ok

    try:
        from app.services.telegram_notifier import telegram_notifier
    except Exception:
        return

    if not current_ok:
        # Degraded: send at most one alert per NOTION_DEGRADED_ALERT_COOLDOWN_MINUTES
        now = datetime.now(timezone.utc)
        if _last_degraded_alert_at is not None:
            if (now - _last_degraded_alert_at) < timedelta(minutes=NOTION_DEGRADED_ALERT_COOLDOWN_MINUTES):
                return
        if not getattr(telegram_notifier, "enabled", False):
            return
        msg = (
            "⚠️ Notion integration degraded on LAB\n"
            f"env_ok={health.get('env_ok')} env_source={health.get('env_source') or '?'}\n"
            f"last_error={str(health.get('last_error') or '')[:200]}"
        )
        try:
            telegram_notifier.send_message(msg, chat_destination="ops")
            _last_degraded_alert_at = now
            logger.info("notion_health_alert sent degraded")
        except Exception as e:
            logger.warning("notion_health_alert send failed: %s", e)
        return

    # Healthy: if we just recovered, send one recovery alert
    if previous is False:
        if not getattr(telegram_notifier, "enabled", False):
            return
        try:
            telegram_notifier.send_message("✅ Notion integration recovered", chat_destination="ops")
            logger.info("notion_health_alert sent recovered")
        except Exception as e:
            logger.warning("notion_health_alert recovered send failed: %s", e)
