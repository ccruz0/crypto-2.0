import hmac
import os
from fastapi import Header, HTTPException
from typing import Optional

# API key for x-api-key header: ATP_API_KEY (production) or INTERNAL_API_KEY, fallback demo-key for local
def _get_expected_api_key() -> str:
    return (
        (os.getenv("ATP_API_KEY") or os.getenv("INTERNAL_API_KEY") or "").strip()
        or "demo-key"
    )


async def get_current_user(x_api_key: Optional[str] = Header(None)):
    """Validate API key from header (x-api-key or X-API-Key). Reads ATP_API_KEY or INTERNAL_API_KEY from env."""
    expected = _get_expected_api_key()
    provided = (x_api_key or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return {"user": "demo"}

