"""Amazon Bedrock client for Claude (Jarvis) — Phase 2 rewrite (P2-R1).

What changed versus the legacy client:

  * Transport is the native ``converse()`` API. The legacy ``invoke_model``
    call with a hand-built request body is gone.
  * Structured output uses **forced tool-use** (``toolChoice``): the JSON shape
    is part of the API contract and arrives as a parsed Python dict. The
    4-layer regex extractor (``extract_planner_json_object``) is deleted —
    there is no parsing step left to break.
  * Retry with exponential backoff on throttling; fail-fast on access errors.
  * Model selection goes through the Phase 2 model router (P2-R2) and every
    call records token usage in the cost tracker (P2-R4) — ``converse()``
    returns usage natively on each response.

Compatibility contract (unchanged on purpose):

  * ``ask_bedrock(prompt) -> str`` — same signature, same failure behavior:
    logs and returns ``""``; never raises on AWS/network problems.
  * New: ``ask_bedrock_json(prompt, ...) -> dict | None`` for structured
    consumers; returns ``None`` on failure, never raises.
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any

from app.jarvis import cost_tracker
from app.jarvis.model_router import fallback_chain

logger = logging.getLogger(__name__)

DEFAULT_REGION = "us-east-1"

_MAX_TOKENS = 4096
_MAX_ATTEMPTS_PER_MODEL = 3
_BACKOFF_BASE_SECONDS = 0.8

# Default schema for structured calls when the caller does not supply one:
# a single free-shape JSON object. Consumers validate fields themselves,
# exactly as they did before.
_ANY_OBJECT_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": True}

_STRUCTURED_TOOL_NAME = "emit_json"


def _bedrock_region() -> str:
    return (os.environ.get("JARVIS_BEDROCK_REGION") or DEFAULT_REGION).strip()


def _boto3_client():
    """Import boto3 lazily so environments without AWS deps degrade gracefully."""
    import boto3  # noqa: PLC0415 — optional failure surface for tests without AWS

    return boto3.client("bedrock-runtime", region_name=_bedrock_region())


def _is_throttle(error_code: str) -> bool:
    return error_code in {"ThrottlingException", "TooManyRequestsException", "ServiceQuotaExceededException"}


def _converse(
    *,
    prompt: str,
    task: str,
    agent: str,
    mission_id: str | None,
    tool_schema: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Shared transport: one logical call with retry/backoff and model fallback.

    Returns the raw converse() response dict, or None on failure. Never raises.
    """
    try:
        from botocore.exceptions import BotoCoreError, ClientError  # noqa: PLC0415
    except ImportError as e:
        logger.warning("botocore not available: %s", e)
        return None

    try:
        client = _boto3_client()
    except Exception as e:  # noqa: BLE001 — boto3 import/client construction failure
        logger.warning("bedrock client unavailable: %s", e)
        return None

    request: dict[str, Any] = {
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": _MAX_TOKENS},
    }
    if tool_schema is not None:
        request["toolConfig"] = {
            "tools": [
                {
                    "toolSpec": {
                        "name": _STRUCTURED_TOOL_NAME,
                        "description": "Return the answer as a single JSON object.",
                        "inputSchema": {"json": tool_schema},
                    }
                }
            ],
            "toolChoice": {"tool": {"name": _STRUCTURED_TOOL_NAME}},
        }

    for model_id in fallback_chain(task):
        for attempt in range(1, _MAX_ATTEMPTS_PER_MODEL + 1):
            try:
                response = client.converse(modelId=model_id, **request)
            except ClientError as e:
                code = str(e.response.get("Error", {}).get("Code") or "")
                if _is_throttle(code) and attempt < _MAX_ATTEMPTS_PER_MODEL:
                    delay = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
                    logger.warning(
                        "bedrock throttled model=%s attempt=%d/%d; retrying in %.2fs",
                        model_id, attempt, _MAX_ATTEMPTS_PER_MODEL, delay,
                    )
                    time.sleep(delay)
                    continue
                if _is_throttle(code):
                    logger.warning("bedrock throttled model=%s; trying next model in chain", model_id)
                    break  # next model in fallback chain
                kind = classify_bedrock_error(e)
                logger.warning(
                    "bedrock converse failed model=%s code=%s class=%s: %s",
                    model_id, code, kind, e,
                )
                if kind == "model_not_found":
                    break  # this model is unavailable; try the next in the chain
                return None  # access/account/validation errors: fail fast, no blind retries
            except (BotoCoreError, OSError) as e:
                logger.warning(
                    "bedrock transport error model=%s class=%s: %s",
                    model_id, classify_bedrock_error(e), e,
                )
                return None
            usage = response.get("usage") or {}
            cost_tracker.record_usage(
                model_id=model_id,
                input_tokens=int(usage.get("inputTokens") or 0),
                output_tokens=int(usage.get("outputTokens") or 0),
                task=task,
                agent=agent,
                mission_id=mission_id,
            )
            return response
    return None


def classify_bedrock_error(exc: BaseException) -> str:
    """Map a Bedrock/boto failure to a stable operator-facing class.

    ``account_restriction`` is AWS-side (\"Operation not allowed\") and cannot
    be fixed by IAM or instance-role cutover.
    """
    msg = str(exc).lower()
    if "operation not allowed" in msg:
        return "account_restriction"
    if "accessdenied" in msg or "not authorized to perform" in msg:
        return "iam_denied"
    if "resourcenotfound" in msg or "could not resolve the foundation model" in msg:
        return "model_not_found"
    return "request_failed"


def _content_blocks(response: dict[str, Any]) -> list[dict[str, Any]]:
    message = ((response.get("output") or {}).get("message")) or {}
    content = message.get("content")
    return content if isinstance(content, list) else []


def ask_bedrock(prompt: str) -> str:
    """Send a prompt to Claude on Bedrock and return the assistant text.

    On failure (credentials, API, network), logs and returns an empty string.
    Signature and failure contract are byte-compatible with the legacy client.
    """
    text = (prompt or "").strip()
    if not text:
        logger.warning("ask_bedrock called with empty prompt")
        return ""

    response = _converse(prompt=text, task="standard", agent="text", mission_id=None, tool_schema=None)
    if response is None:
        return ""

    parts: list[str] = []
    for block in _content_blocks(response):
        if isinstance(block, dict) and "text" in block:
            parts.append(str(block.get("text") or ""))
    assistant_text = "".join(parts).strip()
    if not assistant_text:
        logger.warning("bedrock converse returned no assistant text")
    return assistant_text


def ask_bedrock_json(
    prompt: str,
    *,
    schema: dict[str, Any] | None = None,
    task: str = "standard",
    agent: str = "unknown",
    mission_id: str | None = None,
) -> dict[str, Any] | None:
    """Structured call: JSON arrives as a parsed dict via forced tool-use.

    There is no text-to-JSON parsing step — the shape is enforced by the
    ``toolChoice`` contract on the Bedrock side. Returns ``None`` on failure;
    never raises on AWS/network problems.
    """
    text = (prompt or "").strip()
    if not text:
        logger.warning("ask_bedrock_json called with empty prompt")
        return None

    response = _converse(
        prompt=text,
        task=task,
        agent=agent,
        mission_id=mission_id,
        tool_schema=schema or _ANY_OBJECT_SCHEMA,
    )
    if response is None:
        return None

    for block in _content_blocks(response):
        if not isinstance(block, dict):
            continue
        tool_use = block.get("toolUse")
        if isinstance(tool_use, dict):
            payload = tool_use.get("input")
            if isinstance(payload, dict):
                return payload
    logger.warning("bedrock converse returned no structured toolUse block")
    return None
