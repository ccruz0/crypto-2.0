#!/usr/bin/env python3
"""
Minimal Notion connection check for the AI Task System database.

Usage:
  python backend/scripts/check_notion_connection.py

Checks:
- NOTION_API_KEY and NOTION_TASK_DB are present
- integration can read database metadata
- integration can query the database

Exit codes:
- 0: connection/read access OK
- 1: missing env or Notion access/query failure
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _load_local_env_file() -> None:
    """
    Best-effort load of local env file values into os.environ.

    Keeps existing process env values unchanged and only fills missing keys.
    This avoids requiring `source .env` for simple operator checks.
    """
    candidates = (Path(".env"), Path("backend/.env"))
    for env_path in candidates:
        if not env_path.exists():
            continue
        try:
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if not key:
                    continue
                value = value.strip().strip("'").strip('"')
                os.environ.setdefault(key, value)
        except Exception:
            continue
        break


def _mask_secret(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "<missing>"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def main() -> int:
    _load_local_env_file()
    api_key = (os.environ.get("NOTION_API_KEY") or "").strip()
    database_id = (os.environ.get("NOTION_TASK_DB") or "").strip()

    print("=== Notion Connection Check ===")
    print(f"NOTION_API_KEY: {'set' if api_key else 'missing'} ({_mask_secret(api_key)})")
    print(f"NOTION_TASK_DB: {'set' if database_id else 'missing'} ({_mask_secret(database_id)})")

    if not api_key or not database_id:
        print("RESULT: FAIL - required environment variables are missing.")
        print("Set NOTION_API_KEY and NOTION_TASK_DB, then rerun.")
        return 1

    headers = _headers(api_key)

    try:
        with httpx.Client(timeout=15.0) as client:
            db_resp = client.get(f"{NOTION_API_BASE}/databases/{database_id}", headers=headers)
            if db_resp.status_code != 200:
                print(f"RESULT: FAIL - database metadata read failed (HTTP {db_resp.status_code}).")
                print(
                    "Likely causes: invalid token, wrong DB ID, DB not shared with integration, or missing Notion permissions."
                )
                return 1

            query_payload = {"page_size": 1}
            query_resp = client.post(
                f"{NOTION_API_BASE}/databases/{database_id}/query",
                json=query_payload,
                headers=headers,
            )
            if query_resp.status_code != 200:
                print(f"RESULT: FAIL - database query failed (HTTP {query_resp.status_code}).")
                print("Likely causes: integration lacks read access to this database schema.")
                return 1

            data = query_resp.json()
            sample_count = len(data.get("results") or [])
            print("RESULT: PASS - Notion database access is working.")
            print(f"Summary: metadata read OK, query OK, sample rows returned: {sample_count}.")
            return 0
    except httpx.TimeoutException:
        print("RESULT: FAIL - request timed out while contacting Notion.")
        return 1
    except httpx.RequestError as exc:
        print(f"RESULT: FAIL - network/request error contacting Notion: {exc.__class__.__name__}.")
        return 1
    except Exception as exc:
        print(f"RESULT: FAIL - unexpected error: {exc.__class__.__name__}.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
