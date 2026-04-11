"""Amazon Bedrock client for Claude (Jarvis planner)."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_REGION = "us-east-1"
DEFAULT_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"


def _bedrock_region() -> str:
    return (os.environ.get("JARVIS_BEDROCK_REGION") or DEFAULT_REGION).strip()


def _model_id() -> str:
    return (os.environ.get("JARVIS_BEDROCK_MODEL_ID") or DEFAULT_MODEL_ID).strip()


def extract_planner_json_object(text: str) -> dict[str, Any] | None:
    """
    Extract the first JSON object from noisy model output.

    Tolerates prose before/after, markdown fences, and attempts bracket-balanced
    extraction when naive slicing fails.
    """
    raw = (text or "").strip()
    if not raw:
        return None

    # Prefer fenced ```json ... ```
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()

    # Whole string
    obj = _try_parse_json_object(raw)
    if obj is not None:
        return obj

    # First balanced {...}
    balanced = _extract_first_balanced_object(raw)
    if balanced:
        obj = _try_parse_json_object(balanced)
        if obj is not None:
            return obj

    # Scan from each '{' (legacy fallback for malformed but loadable slices)
    for i, ch in enumerate(raw):
        if ch != "{":
            continue
        for j in range(len(raw), i + 1, -1):
            if j <= i or raw[j - 1] != "}":
                continue
            chunk = raw[i:j]
            obj = _try_parse_json_object(chunk)
            if obj is not None:
                return obj
    return None


def _try_parse_json_object(s: str) -> dict[str, Any] | None:
    try:
        val = json.loads(s)
    except json.JSONDecodeError:
        return None
    return val if isinstance(val, dict) else None


def _extract_first_balanced_object(s: str) -> str | None:
    """Return substring of first {...} with balanced braces outside strings."""
    start = -1
    depth = 0
    in_str = False
    escape = False
    for i, c in enumerate(s):
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            continue
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                return s[start : i + 1]
    return None


def ask_bedrock(prompt: str) -> str:
    """
    Send a user/assistant-style prompt to Claude on Bedrock and return assistant text.

    On failure (credentials, API, network, parse), logs and returns an empty string.
    """
    text = (prompt or "").strip()
    if not text:
        logger.warning("ask_bedrock called with empty prompt")
        return ""

    try:
        import boto3  # noqa: PLC0415 — optional failure surface for tests without AWS
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as e:
        logger.warning("boto3 not available: %s", e)
        return ""

    region = _bedrock_region()
    model_id = _model_id()

    body: dict[str, Any] = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }

    try:
        client = boto3.client("bedrock-runtime", region_name=region)
        response = client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        raw = response.get("body")
        if raw is None:
            logger.error("bedrock invoke_model returned no body")
            return ""
        payload_bytes = raw.read() if hasattr(raw, "read") else raw
        payload: Any = json.loads(payload_bytes)
    except (ClientError, BotoCoreError, OSError) as e:
        logger.warning("Bedrock request failed: %s", e)
        return ""
    except json.JSONDecodeError as e:
        logger.warning("Bedrock response JSON decode failed: %s", e)
        return ""

    assistant_text = _extract_assistant_text(payload)
    if not assistant_text:
        logger.warning("Bedrock response had no assistant text: keys=%s", list(payload)[:10])
    return assistant_text


def _extract_assistant_text(payload: dict[str, Any]) -> str:
    """Pull plain text from Bedrock Claude 3 response body."""
    content = payload.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and "text" in block:
                parts.append(str(block.get("text") or ""))
        return "".join(parts).strip()

    if "completion" in payload:
        return str(payload.get("completion") or "").strip()

    return ""
