#!/usr/bin/env python3
"""
One-time helper: obtain a Google Ads OAuth refresh token for Jarvis.

Why this exists
---------------
Jarvis Google Ads diagnostics use the standard OAuth installed/web client flow:
  - client_id / client_secret from JARVIS_GOOGLE_ADS_CREDENTIALS_JSON (OAuth client JSON)
  - refresh token from JARVIS_GOOGLE_ADS_REFRESH_TOKEN (runtime env)

This script is NOT part of normal mission execution. Run it manually when onboarding.

Official scope (read-only for Google Ads API)
---------------------------------------------
https://www.googleapis.com/auth/adwords

Prerequisites
-------------
- OAuth client JSON downloaded from Google Cloud Console (Desktop / installed app type recommended).
- Env var JARVIS_GOOGLE_ADS_CREDENTIALS_JSON must point to that JSON file path.
- A browser available on the machine where you run this script (local workstation is easiest).

Operator flow
-------------
1) Export the path to your OAuth client JSON:
     export JARVIS_GOOGLE_ADS_CREDENTIALS_JSON=/path/to/client_secret.json

2) Run this script on a machine with a browser:
     python3 backend/scripts/generate_google_ads_refresh_token.py

3) Complete the browser consent flow.

4) Copy the printed REFRESH TOKEN into production secrets:
     /home/ubuntu/crypto-2.0/secrets/runtime.env
   as:
     JARVIS_GOOGLE_ADS_REFRESH_TOKEN=<paste>

5) Restart backend-aws (production):
     cd /home/ubuntu/crypto-2.0
     sudo docker compose --profile aws up -d backend-aws

Security
--------
- Do not commit refresh tokens.
- Do not paste tokens into chat logs.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

GOOGLE_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"


def _die(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def _normalize_oauth_client_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Accept OAuth client JSON as either:
      - {"installed": {...}} or {"web": {...}}  (Google client secret download)
      - {"client_id": "...", "client_secret": "..."}  (flattened)
    Return a dict suitable for google_auth_oauthlib InstalledAppFlow.from_client_config.
    """
    if isinstance(raw.get("installed"), dict):
        return {"installed": raw["installed"]}
    if isinstance(raw.get("web"), dict):
        return {"web": raw["web"]}
    if "client_id" in raw and "client_secret" in raw:
        return {"installed": dict(raw)}
    _die(
        "OAuth client JSON must be 'installed' or 'web' format from Google Cloud, "
        "or include top-level client_id + client_secret."
    )


def main() -> int:
    creds_path = (os.getenv("JARVIS_GOOGLE_ADS_CREDENTIALS_JSON") or "").strip()
    if not creds_path:
        _die("Missing JARVIS_GOOGLE_ADS_CREDENTIALS_JSON (path to OAuth client JSON).")

    path = Path(creds_path)
    if not path.is_file():
        _die(f"OAuth client JSON file not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _die(f"Failed to read OAuth client JSON: {exc}")

    if not isinstance(raw, dict):
        _die("OAuth client JSON must be a JSON object.")

    if raw.get("type") == "service_account":
        _die(
            "This file is a service-account JSON. Google Ads OAuth needs an OAuth client JSON "
            "(installed/web) from Google Cloud Console."
        )

    client_cfg = _normalize_oauth_client_dict(raw)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    except Exception as exc:
        _die(
            "google_auth_oauthlib is required. Install deps (e.g. pip install google-auth-oauthlib) "
            f"or run from the backend container image. Import error: {exc}"
        )

    port_env = (os.getenv("GOOGLE_OAUTH_LOCAL_PORT") or "").strip()
    port = int(port_env) if port_env.isdigit() else 0

    open_browser = (os.getenv("GOOGLE_OAUTH_OPEN_BROWSER") or "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        tmp.write(json.dumps(client_cfg))
        tmp_path = tmp.name

    try:
        flow = InstalledAppFlow.from_client_secrets_file(tmp_path, scopes=[GOOGLE_ADS_SCOPE])
        creds = flow.run_local_server(port=port, open_browser=open_browser)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if not creds or not getattr(creds, "refresh_token", None):
        _die(
            "No refresh_token returned. Common causes:\n"
            "- OAuth consent screen / scopes not approved for this client\n"
            "- User did not grant offline access (re-run and ensure consent completes)\n"
            "- Wrong OAuth client type (prefer Desktop/Installed app client)\n"
        )

    print("")
    print("SUCCESS")
    print("Add this line to /home/ubuntu/crypto-2.0/secrets/runtime.env (or your env file):")
    print("")
    print(f"JARVIS_GOOGLE_ADS_REFRESH_TOKEN={creds.refresh_token}")
    print("")
    print("Then restart backend-aws.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
