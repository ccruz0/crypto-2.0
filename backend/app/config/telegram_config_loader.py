"""
Telegram configuration loader. Discovers bot token and chat ID from
environment, env files, and AWS SSM.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypedDict

try:
    import boto3
except ImportError:
    boto3 = None  # type: ignore[assignment]

# Repo root: backend/app/config -> app -> backend -> repo root
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parent.parent.parent.parent


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse .env-style file. Format: KEY=value. Ignore comments and blank lines."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return result
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if key:
                if (val.startswith('"') and val.endswith('"')) or (
                    val.startswith("'") and val.endswith("'")
                ):
                    val = val[1:-1]
                result[key] = val
    return result


def _get_from_env_file(path: Path, key: str) -> str | None:
    """Get value for key from env file."""
    d = _parse_env_file(path)
    v = d.get(key) or None
    return v.strip() if v and v.strip() else None


def _get_from_ssm(param_name: str) -> str | None:
    """Get parameter from AWS SSM. Returns None if boto3 unavailable or param missing."""
    if boto3 is None:
        return None
    region = (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "ap-southeast-1"
    )
    try:
        client = boto3.client("ssm", region_name=region)
        resp = client.get_parameter(Name=param_name, WithDecryption=True)
        v = (resp.get("Parameter") or {}).get("Value") or None
        return v.strip() if v and v.strip() else None
    except Exception:
        return None


def _discover_bot_token() -> tuple[str | None, str]:
    """Discover TELEGRAM_BOT_TOKEN. Returns (value, source_description)."""
    # 1. Environment variable
    v = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if v:
        return v, "environment variable"

    # 2. secrets/runtime.env
    p = _REPO_ROOT / "secrets" / "runtime.env"
    v = _get_from_env_file(p, "TELEGRAM_BOT_TOKEN")
    if v:
        return v, "secrets/runtime.env"

    # 3. .env
    p = _REPO_ROOT / ".env"
    v = _get_from_env_file(p, "TELEGRAM_BOT_TOKEN")
    if v:
        return v, ".env"

    # 4. .env.aws
    p = _REPO_ROOT / ".env.aws"
    v = _get_from_env_file(p, "TELEGRAM_BOT_TOKEN")
    if v:
        return v, ".env.aws"

    # 5. AWS SSM
    v = _get_from_ssm("/automated-trading-platform/prod/telegram/bot_token")
    if v:
        return v, "AWS SSM"

    return None, "not found"


def _discover_chat_id() -> tuple[str | None, str]:
    """Discover TELEGRAM_CHAT_ID. Returns (value, source_description)."""
    # 1. Environment variable
    v = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if v:
        return v, "environment variable"

    # 2. secrets/runtime.env
    p = _REPO_ROOT / "secrets" / "runtime.env"
    v = _get_from_env_file(p, "TELEGRAM_CHAT_ID")
    if v:
        return v, "secrets/runtime.env"

    # 3. .env
    p = _REPO_ROOT / ".env"
    v = _get_from_env_file(p, "TELEGRAM_CHAT_ID")
    if v:
        return v, ".env"

    # 4. .env.aws
    p = _REPO_ROOT / ".env.aws"
    v = _get_from_env_file(p, "TELEGRAM_CHAT_ID")
    if v:
        return v, ".env.aws"

    # 5. AWS SSM
    v = _get_from_ssm("/automated-trading-platform/prod/telegram/chat_id")
    if v:
        return v, "AWS SSM"

    return None, "not found"


class TelegramConfig(TypedDict):
    """Telegram configuration result."""

    bot_token: str | None
    chat_id: str | None
    sources: dict[str, str]


def load_telegram_config() -> TelegramConfig:
    """
    Load Telegram configuration from all sources.

    Returns:
        {
            "bot_token": str | None,
            "chat_id": str | None,
            "sources": {
                "bot_token": "environment variable" | "secrets/runtime.env" | ...,
                "chat_id": "environment variable" | "secrets/runtime.env" | ...
            }
        }
    """
    token, token_source = _discover_bot_token()
    chat_id, chat_id_source = _discover_chat_id()
    return {
        "bot_token": token,
        "chat_id": chat_id,
        "sources": {
            "bot_token": token_source,
            "chat_id": chat_id_source,
        },
    }
