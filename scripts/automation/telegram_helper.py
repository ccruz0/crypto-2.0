"""Telegram alert helper for Jarvis automations (no secret logging)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .common import REPO_ROOT, load_runtime_env

logger = logging.getLogger(__name__)


def _resolve_chat_id() -> Optional[str]:
    return (
        (os.getenv("TELEGRAM_CHAT_ID_OPS") or "").strip()
        or (os.getenv("TELEGRAM_ALERT_CHAT_ID") or "").strip()
        or (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
        or (os.getenv("TELEGRAM_CHAT_ID_AWS") or "").strip()
        or None
    )


def _resolve_bot_token() -> Optional[str]:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_ALERT_BOT_TOKEN") or "").strip()
    if token:
        return token

    encrypted = (os.getenv("TELEGRAM_BOT_TOKEN_ENCRYPTED") or "").strip()
    if not encrypted:
        return None

    decrypt_script = REPO_ROOT / "scripts" / "diag" / "decrypt_telegram_token_for_alert.py"
    if not decrypt_script.is_file():
        return None

    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        proc = subprocess.run(
            ["python3", str(decrypt_script), tmp_path],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=str(REPO_ROOT),
            check=False,
        )
        if proc.returncode != 0:
            logger.warning("Telegram token decryption failed (exit %s)", proc.returncode)
            return None
        token = Path(tmp_path).read_text(encoding="utf-8").strip()
        return token or None
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass


def send_telegram_alert(text: str, *, dry_run: bool = False) -> bool:
    """
    Send a short ops Telegram message.

    Returns True when sent (or dry-run would have sent). Never logs tokens.
    """
    load_runtime_env()

    chat_id = _resolve_chat_id()
    if not chat_id:
        logger.warning("Telegram chat id not configured; skip send")
        return False

    if dry_run:
        preview = text if len(text) <= 500 else text[:500] + "…"
        logger.info("DRY-RUN Telegram -> chat_id=%s: %s", chat_id, preview)
        return True

    token = _resolve_bot_token()
    if not token:
        logger.warning("Telegram bot token not configured; skip send")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        req = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("ok"):
            logger.info("Telegram alert sent")
            return True
        logger.warning("Telegram API error: %s", data.get("description", "unknown"))
        return False
    except HTTPError as exc:
        logger.warning("Telegram HTTP error: %s", exc.code)
        return False
    except URLError as exc:
        logger.warning("Telegram network error: %s", exc.reason)
        return False
    except Exception as exc:  # pragma: no cover
        logger.warning("Telegram send failed: %s", type(exc).__name__)
        return False
