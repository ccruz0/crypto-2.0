"""
Admin-only API endpoints
Requires X-Admin-Key header matching ADMIN_ACTIONS_KEY env var
"""
import os
import logging
import time
import re
from datetime import datetime, timezone
from fastapi import APIRouter, Header, HTTPException, Depends, Body
from typing import Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.telegram_notifier import telegram_notifier
from app.services.system_health import record_telegram_send_result
from app.services.signal_monitor import signal_monitor_service
from app.models.watchlist_master import WatchlistItem

router = APIRouter()


class EvaluateSymbolBody(BaseModel):
    symbol: str = "BTC_USDT"


class RotateAdminKeyBody(BaseModel):
    new_admin_key: str


class SecretIntakeBody(BaseModel):
    env_var: str
    value: str
    persist_ssm: bool = False


logger = logging.getLogger(__name__)

_MIN_ADMIN_KEY_LEN = 16

# Rate limiting: last test timestamp (in-memory, per-process)
_last_test_telegram_ts: Optional[float] = None
_TEST_TELEGRAM_COOLDOWN_SECONDS = 60


_TELEGRAM_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")
_PROD_INSTANCE_ID = "i-087953603011543c5"
_PROD_REGION = "ap-southeast-1"
_PROD_TELEGRAM_TOKEN_PARAM = "/automated-trading-platform/prod/telegram/bot_token"


class TelegramTokenUpdateBody(BaseModel):
    token: str


def _mask_token_suffix(token: str) -> str:
    token = (token or "").strip()
    if not token:
        return "***"
    return f"***{token[-8:]}"


def _validate_telegram_token_shape(token: str) -> bool:
    return bool(_TELEGRAM_TOKEN_RE.match((token or "").strip()))


def _run_prod_runtime_refresh_via_ssm(ssm_client) -> tuple[bool, str]:
    """Update PROD runtime.env from SSM and restart backend-aws (no token in command body)."""
    script = r"""
set -euo pipefail
cd /home/ubuntu/automated-trading-platform
python3 - <<'PY'
import os
import re
import boto3

PARAM_NAME = "/automated-trading-platform/prod/telegram/bot_token"
RUNTIME_ENV = "/home/ubuntu/automated-trading-platform/secrets/runtime.env"
REGION = "ap-southeast-1"

ssm = boto3.client("ssm", region_name=REGION)
token = ssm.get_parameter(Name=PARAM_NAME, WithDecryption=True)["Parameter"]["Value"].strip()
if not token:
    raise SystemExit("empty token from ssm")

lines = []
if os.path.isfile(RUNTIME_ENV):
    with open(RUNTIME_ENV, "r", encoding="utf-8") as f:
        lines = f.readlines()

updated = []
found = False
found_bot = False
found_atp_control = False
for line in lines:
    if line.startswith("TELEGRAM_BOT_TOKEN="):
        updated.append("TELEGRAM_BOT_TOKEN=" + token + "\n")
        found_bot = True
    elif line.startswith("TELEGRAM_ATP_CONTROL_BOT_TOKEN="):
        updated.append("TELEGRAM_ATP_CONTROL_BOT_TOKEN=" + token + "\n")
        found_atp_control = True
    else:
        updated.append(line)

if not found_bot:
    if updated and not updated[-1].endswith("\n"):
        updated.append("\n")
    updated.append("TELEGRAM_BOT_TOKEN=" + token + "\n")
if not found_atp_control:
    updated.append("TELEGRAM_ATP_CONTROL_BOT_TOKEN=" + token + "\n")

with open(RUNTIME_ENV, "w", encoding="utf-8") as f:
    f.writelines(updated)
PY
docker compose --profile aws restart backend-aws
"""
    resp = ssm_client.send_command(
        InstanceIds=[_PROD_INSTANCE_ID],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [script]},
        TimeoutSeconds=180,
    )
    command_id = resp.get("Command", {}).get("CommandId")
    if not command_id:
        return False, "no CommandId from SSM send-command"

    for _ in range(120):
        time.sleep(1)
        try:
            inv = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=_PROD_INSTANCE_ID,
            )
        except Exception:
            continue
        status = (inv.get("Status") or "").strip()
        if status in ("Success", "Failed", "Cancelled", "TimedOut"):
            if status == "Success":
                return True, ""
            err = (inv.get("StandardErrorContent") or inv.get("StandardOutputContent") or "").strip()
            return False, (err[:300] or f"ssm status={status}")

    return False, "runtime refresh timed out"


def verify_admin_key(x_admin_key: Optional[str] = Header(None)) -> str:
    """Verify admin key from header"""
    expected_key = os.getenv("ADMIN_ACTIONS_KEY")
    
    if not expected_key:
        logger.warning("ADMIN_ACTIONS_KEY not set - admin endpoints disabled")
        raise HTTPException(status_code=401, detail="Admin actions not configured")
    
    if not x_admin_key or x_admin_key != expected_key:
        logger.warning(f"Invalid admin key attempt (header present: {x_admin_key is not None})")
        raise HTTPException(status_code=401, detail="unauthorized")
    
    return x_admin_key


def compute_admin_secrets_status_dict() -> dict:
    """Shared JSON for secrets banner (GET /api/admin/secrets-status and monitoring alias)."""
    try:
        from app.services.required_secrets_registry import evaluate_requirements

        return evaluate_requirements()
    except Exception as exc:
        logger.warning("compute_admin_secrets_status_dict: registry unavailable: %s", type(exc).__name__)
        try:
            from app.core.environment import is_atp_trading_only, is_aws as _is_aws
        except Exception:

            def _is_aws() -> bool:
                return False

            def is_atp_trading_only() -> bool:
                return False

        return {
            "overall": "ok",
            "missing": [],
            "skipped_count": 0,
            "context": {
                "atp_trading_only": bool(is_atp_trading_only()),
                "environment": (os.getenv("ENVIRONMENT") or "unknown").strip(),
                "aws": bool(_is_aws()),
                "github_legacy_pat_active": (os.getenv("ALLOW_LEGACY_GITHUB_PAT") or "").lower() in ("1", "true", "yes"),
                "github_app_client_id_status": None,
            },
            "automation_readiness": {
                "applicable": False,
                "missing": [],
                "note": "Secrets registry is not available on this server build.",
            },
        }


@router.get("/admin/secrets-status")
def admin_secrets_status(admin_key: str = Depends(verify_admin_key)):
    """Return required-secrets evaluation for the trading dashboard (admin-only)."""
    return compute_admin_secrets_status_dict()


def compute_admin_recovery_dict() -> dict:
    try:
        from app.services.secret_recovery import recovery_status_payload

        return recovery_status_payload()
    except Exception as exc:
        logger.warning("compute_admin_recovery_dict: %s", type(exc).__name__)
        return {
            "auto_restart_enabled": False,
            "compose_project_configured": False,
            "recovery_runnable": False,
            "note": "Recovery module unavailable on this build.",
        }


@router.get("/admin/recovery-status")
def admin_recovery_status(admin_key: str = Depends(verify_admin_key)):
    return compute_admin_recovery_dict()


def perform_secrets_intake(body: SecretIntakeBody) -> dict:
    """
    Persist one allowlisted env var to runtime.env (shared by /admin and /monitoring routes).
    Caller must have verified X-Admin-Key already.
    """
    from app.jarvis.secure_runtime_env_write import persist_env_var_value

    key = (body.env_var or "").strip()
    val = (body.value or "").strip()
    if not key or not val:
        raise HTTPException(status_code=400, detail="env_var_and_value_required")

    try:
        from app.services.required_secrets_registry import is_allowed_intake_key
    except Exception:

        def is_allowed_intake_key(name: str) -> bool:  # type: ignore[misc]
            return name in ("GITHUB_APP_CLIENT_ID",)

    if not is_allowed_intake_key(key):
        raise HTTPException(status_code=400, detail="env_var_not_allowed_for_intake")

    if body.persist_ssm:
        logger.info("secrets_intake persist_ssm=1 for %s (SSM path optional; runtime.env always updated)", key)

    try:
        persist_env_var_value(key, val)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except OSError as exc:
        logger.error("secrets_intake persist OSError env_var=%s: %s", key, exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="runtime_env_write_failed (check permissions on secrets/ and runtime.env)",
        ) from exc

    os.environ[key] = val
    return {"ok": True, "message": "Saved to runtime.env"}


@router.post("/admin/secrets-intake")
def admin_secrets_intake(
    body: SecretIntakeBody = Body(...),
    _verified: str = Depends(verify_admin_key),
):
    """Persist one allowlisted env var to runtime.env (admin-only)."""
    return perform_secrets_intake(body)


@router.post("/admin/recovery-apply")
def admin_recovery_apply(admin_key: str = Depends(verify_admin_key)):
    try:
        from app.services.secret_recovery import apply_backend_recovery
    except Exception:
        raise HTTPException(
            status_code=501,
            detail="secret_recovery_not_available_on_this_build",
        ) from None
    try:
        return apply_backend_recovery()
    except Exception as exc:
        logger.error("admin_recovery_apply failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="recovery_apply_failed") from exc


@router.post("/admin/rotate-admin-key")
def rotate_admin_key(
    body: RotateAdminKeyBody = Body(...),
    admin_key: str = Depends(verify_admin_key),
):
    """
    Rotate ADMIN_ACTIONS_KEY: verifies current X-Admin-Key, writes new value to runtime.env,
    and updates the running process environment so the session can continue without restart.
    """
    from app.jarvis.secure_runtime_env_write import persist_env_var_value

    new_k = (body.new_admin_key or "").strip()
    if len(new_k) < _MIN_ADMIN_KEY_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"new_admin_key_too_short (min {_MIN_ADMIN_KEY_LEN} characters)",
        )
    if new_k == admin_key:
        raise HTTPException(status_code=400, detail="new_admin_key_same_as_current")

    try:
        persist_env_var_value("ADMIN_ACTIONS_KEY", new_k)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve

    os.environ["ADMIN_ACTIONS_KEY"] = new_k
    logger.info("ADMIN_ACTIONS_KEY rotated via /admin/rotate-admin-key")
    return {"ok": True, "message": "Admin key updated. Use the new key from now on (also saved to runtime.env)."}


@router.post("/admin/test-telegram")
async def test_telegram(
    admin_key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db)
):
    """
    Send a test Telegram message (admin-only, rate-limited)
    
    Requires:
    - Header: X-Admin-Key: <ADMIN_ACTIONS_KEY>
    
    Returns:
    - {"ok": true} on success
    - {"ok": false, "error": "<reason>"} on failure
    """
    global _last_test_telegram_ts
    
    # Rate limiting check
    now = time.time()
    if _last_test_telegram_ts is not None:
        time_since_last = now - _last_test_telegram_ts
        if time_since_last < _TEST_TELEGRAM_COOLDOWN_SECONDS:
            remaining = int(_TEST_TELEGRAM_COOLDOWN_SECONDS - time_since_last)
            logger.warning(f"Test telegram rate limited (cooldown: {remaining}s remaining)")
            raise HTTPException(
                status_code=429,
                detail=f"rate_limited (cooldown: {remaining}s remaining)"
            )
    
    try:
        # Send test message
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        message = f"✅ TEST: Telegram is working (AWS) — {timestamp}"
        
        if not telegram_notifier.enabled:
            return {"ok": False, "error": "telegram_disabled"}
        
        success = telegram_notifier.send_message(message, origin="AWS")
        record_telegram_send_result(success)
        
        if success:
            _last_test_telegram_ts = now
            logger.info("Test Telegram message sent successfully")
            return {"ok": True}
        else:
            return {"ok": False, "error": "send_failed"}
    
    except Exception as e:
        logger.error(f"Error sending test Telegram message: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


@router.post("/admin/telegram/atp-control-token")
def update_atp_control_telegram_token(
    body: TelegramTokenUpdateBody = Body(...),
    admin_key: str = Depends(verify_admin_key),
):
    """
    Admin-only: update ATP Control Telegram bot token in PROD SSM and refresh runtime.
    Never logs or returns full token.
    """
    token = (body.token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="token_required")
    if not _validate_telegram_token_shape(token):
        raise HTTPException(status_code=400, detail="invalid_telegram_token_format")

    masked = _mask_token_suffix(token)
    try:
        import boto3

        ssm = boto3.client("ssm", region_name=_PROD_REGION)
        ssm.put_parameter(
            Name=_PROD_TELEGRAM_TOKEN_PARAM,
            Value=token,
            Type="SecureString",
            Overwrite=True,
        )

        ok, err = _run_prod_runtime_refresh_via_ssm(ssm)
        if not ok:
            logger.error(
                "telegram_token_update_failed mask=%s reason=%s",
                masked,
                err[:200],
            )
            raise HTTPException(status_code=500, detail=f"runtime_refresh_failed ({err[:120]})")

        logger.info(
            "telegram_token_update_success mask=%s param=%s",
            masked,
            _PROD_TELEGRAM_TOKEN_PARAM,
        )
        return {
            "ok": True,
            "message": "ATP Control Telegram token updated",
            "token_masked": masked,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("telegram_token_update_error mask=%s err=%s", masked, str(e)[:200], exc_info=True)
        raise HTTPException(status_code=500, detail="token_update_failed")


@router.post("/admin/debug/evaluate-symbol")
def evaluate_symbol(
    body: EvaluateSymbolBody = Body(...),
    admin_key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """
    Trigger signal evaluation for one symbol (admin-only, for smoke/E2E).
    Requires X-Admin-Key header. Writes to watchlist_signal_state and may send Telegram.
    """
    symbol = (body.symbol or "BTC_USDT").strip().upper()
    try:
        watchlist_item = (
            db.query(WatchlistItem)
            .filter(WatchlistItem.symbol == symbol, WatchlistItem.is_deleted == False)
            .first()
        )
        if not watchlist_item:
            return {"ok": False, "error": f"symbol_not_in_watchlist:{symbol}"}
        signal_monitor_service._check_signal_for_coin_sync(db, watchlist_item)
        return {"ok": True, "symbol": symbol}
    except Exception as e:
        logger.warning(f"evaluate-symbol {symbol}: {e}", exc_info=True)
        return {"ok": False, "error": str(e), "symbol": symbol}



