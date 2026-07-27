"""Shared auth for brief endpoints (X-Brief-Key)."""

from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import Header, HTTPException


def _expected_brief_key() -> str:
    return (os.getenv("BRIEF_API_KEY") or "").strip()


async def require_brief_key(x_brief_key: Optional[str] = Header(None, alias="X-Brief-Key")) -> None:
    """Validate X-Brief-Key against BRIEF_API_KEY. Never log the key."""
    expected = _expected_brief_key()
    if not expected:
        raise HTTPException(status_code=503, detail="brief_not_configured")
    provided = (x_brief_key or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="unauthorized")
