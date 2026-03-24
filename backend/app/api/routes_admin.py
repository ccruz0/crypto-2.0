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
logger = logging.getLogger(__name__)

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
for line in lines:
    if line.startswith("TELEGRAM_BOT_TOKEN="):
        updated.append("TELEGRAM_BOT_TOKEN=" + token + "\n")
        found = True
    else:
        updated.append(line)

if not found:
    if updated and not updated[-1].endswith("\n"):
        updated.append("\n")
    updated.append("TELEGRAM_BOT_TOKEN=" + token + "\n")

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



