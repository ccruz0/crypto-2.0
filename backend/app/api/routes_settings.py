"""
Settings API: exchange credentials and other runtime configuration.
Credentials are written to secrets/runtime.env; container restart is required for them to take effect.

When ADMIN_ACTIONS_KEY is set, POST /api/settings/* requires X-Admin-Key header (same as admin endpoints).
"""

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional
import os
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


class ExchangeCredentials(BaseModel):
    api_key: str
    api_secret: str


def _optional_admin_key(x_admin_key: Optional[str] = Header(None)):
    """If ADMIN_ACTIONS_KEY is set, require valid X-Admin-Key; otherwise allow (dev)."""
    expected = os.getenv("ADMIN_ACTIONS_KEY")
    if not expected:
        return None
    if not x_admin_key or x_admin_key != expected:
        raise HTTPException(status_code=401, detail="unauthorized")
    return x_admin_key


@router.post("/settings/exchange-credentials")
def set_exchange_credentials(
    payload: ExchangeCredentials,
    _: Optional[str] = Depends(_optional_admin_key),
):
    if not payload.api_key or not payload.api_secret:
        raise HTTPException(status_code=400, detail="Missing values")

    # Write to secrets/runtime.env (must be mounted read-write for persistence)
    env_path = "/app/secrets/runtime.env"

    try:
        lines = []
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()

        # Remove old entries
        lines = [
            l
            for l in lines
            if not l.startswith("EXCHANGE_CUSTOM_API_KEY=")
            and not l.startswith("EXCHANGE_CUSTOM_API_SECRET=")
        ]

        lines.append(f"EXCHANGE_CUSTOM_API_KEY={payload.api_key}\n")
        lines.append(f"EXCHANGE_CUSTOM_API_SECRET={payload.api_secret}\n")

        with open(env_path, "w") as f:
            f.writelines(lines)

        try:
            os.chmod(env_path, 0o600)
        except OSError:
            pass  # Ignore if we cannot chmod (e.g. mounted file)

        logger.info("Exchange credentials updated in runtime.env; restart backend for them to take effect.")
    except PermissionError as e:
        logger.warning("Cannot write to %s: %s", env_path, e)
        raise HTTPException(
            status_code=503,
            detail=(
                "Cannot write to secrets file (permission denied). "
                "On the server ensure secrets/runtime.env is mounted and writable by the backend process, "
                "or add EXCHANGE_CUSTOM_API_KEY and EXCHANGE_CUSTOM_API_SECRET manually and restart the backend."
            ),
        ) from e
    except Exception as e:
        logger.exception("Failed to write exchange credentials")
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {"status": "ok", "message": "Credentials saved. Restart the backend container for them to take effect."}
