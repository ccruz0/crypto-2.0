from fastapi import Header, HTTPException
from typing import Optional

API_KEY = "demo-key"

async def get_current_user(x_api_key: Optional[str] = Header(None)):
    """Validate API key from header"""
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return {"user": "demo"}

