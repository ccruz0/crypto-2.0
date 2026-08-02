#!/usr/bin/env python3
"""One-time interactive Telethon login for the brief Telegram reader.

Usage (PROD):
  docker compose --profile aws exec backend-aws python scripts/telegram_login.py

Writes the session to TELEGRAM_SESSION_PATH (default /data/telegram/hilovivo.session).
Prints only the connected account display name — never the session bytes or api_hash.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


async def _main() -> int:
    try:
        from telethon import TelegramClient
    except ImportError:
        print("ERROR: telethon is not installed in this image", file=sys.stderr)
        return 1

    api_id_raw = (os.getenv("TELEGRAM_API_ID") or "").strip()
    api_hash = (os.getenv("TELEGRAM_API_HASH") or "").strip()
    session_path = (os.getenv("TELEGRAM_SESSION_PATH") or "/data/telegram/hilovivo.session").strip()

    if not api_id_raw or not api_hash:
        print(
            "ERROR: set TELEGRAM_API_ID and TELEGRAM_API_HASH "
            "(from https://my.telegram.org)",
            file=sys.stderr,
        )
        return 1
    try:
        api_id = int(api_id_raw)
    except ValueError:
        print("ERROR: TELEGRAM_API_ID must be an integer", file=sys.stderr)
        return 1

    path = Path(session_path)
    session_dir = path.parent
    session_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(session_dir, 0o700)
    except OSError:
        pass

    # Telethon appends .session to the session name
    session_name = str(path.with_suffix("")) if path.suffix == ".session" else str(path)

    client = TelegramClient(session_name, api_id, api_hash)
    print("Starting Telegram login (phone / code / 2FA if enabled)…")
    await client.start()
    me = await client.get_me()
    first = getattr(me, "first_name", None) or ""
    last = getattr(me, "last_name", None) or ""
    username = getattr(me, "username", None)
    display = f"{first} {last}".strip() or (f"@{username}" if username else "connected")
    print(f"Connected as: {display}")
    await client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
