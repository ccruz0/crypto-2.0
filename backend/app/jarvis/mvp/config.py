"""Environment configuration for Jarvis LangGraph MVP."""

from __future__ import annotations

import os


def _bool_env(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def jarvis_enabled() -> bool:
    return _bool_env("JARVIS_ENABLED", default=True)


def jarvis_dry_run_only() -> bool:
    return _bool_env("JARVIS_DRY_RUN_ONLY", default=True)


def bedrock_region() -> str:
    return (
        os.environ.get("AWS_REGION")
        or os.environ.get("JARVIS_BEDROCK_REGION")
        or "us-east-1"
    ).strip()


def bedrock_model_id() -> str:
    return (
        os.environ.get("BEDROCK_MODEL_ID")
        or os.environ.get("JARVIS_BEDROCK_MODEL_ID")
        or "anthropic.claude-3-sonnet-20240229-v1:0"
    ).strip()
