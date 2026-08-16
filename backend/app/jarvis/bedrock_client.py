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
from collections.abc import Callable
from typing import Any

from app.jarvis import cost_tracker, failure_metrics
from app.jarvis.model_router import fallback_chain

logger = logging.getLogger(__name__)


class BedrockInvocationError(RuntimeError):
    """A Bedrock invocation failed in a way the caller must not ignore.

    Carries a stable ``kind`` (see :func:`classify_bedrock_error`) so callers
    and dashboards can branch on the failure class without string-matching
    messages. Raised instead of the pre-R6 silent ``""`` / ``None``.
    """

    def __init__(self, message: str, *, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


def _fail(message: str, *, kind: str) -> "BedrockInvocationError":
    """Count the failure, log it at ERROR, and build the exception to raise."""
    failure_metrics.record_invocation_failure(kind)
    logger.error("bedrock invocation failed kind=%s: %s", kind, message)
    return BedrockInvocationError(message, kind=kind)

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
) -> dict[str, Any]:
    """Shared transport: one logical call with retry/backoff and model fallback.

    Returns the raw converse() response dict. Raises BedrockInvocationError on
    any failure — it never signals failure by returning None (R6 point 3).
    """
    try:
        from botocore.exceptions import BotoCoreError, ClientError  # noqa: PLC0415
    except ImportError as e:
        raise _fail(f"botocore not available: {e}", kind="boto3_missing") from e

    try:
        client = _boto3_client()
    except Exception as e:  # noqa: BLE001 — boto3 import/client construction failure
        raise _fail(f"bedrock client unavailable: {e}", kind="boto3_missing") from e

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

    last_kind = "no_model_available"
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
                    last_kind = kind
                    break  # this model is unavailable; try the next in the chain
                # access/account/validation errors: fail fast and loudly
                raise _fail(f"converse failed model={model_id} code={code}: {e}", kind=kind) from e
            except (BotoCoreError, OSError) as e:
                raise _fail(
                    f"transport error model={model_id}: {e}",
                    kind=classify_bedrock_error(e),
                ) from e
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
    raise _fail("every model in the fallback chain was unavailable", kind=last_kind)


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

    Fails loudly (R6 point 3): raises :class:`BedrockInvocationError` on any
    AWS/network/model failure instead of returning ``""``. Callers that want to
    degrade should use :func:`ask_bedrock_with_fallback`, which counts the
    degradation so running on heuristics is alertable rather than silent.
    """
    text = (prompt or "").strip()
    if not text:
        raise ValueError("ask_bedrock called with empty prompt")

    response = _converse(prompt=text, task="standard", agent="text", mission_id=None, tool_schema=None)

    parts: list[str] = []
    for block in _content_blocks(response):
        if isinstance(block, dict) and "text" in block:
            parts.append(str(block.get("text") or ""))
    assistant_text = "".join(parts).strip()
    if not assistant_text:
        raise _fail("converse returned no assistant text", kind="no_assistant_text")
    return assistant_text


def ask_bedrock_with_fallback(prompt: str, fallback: Callable[[], str]) -> str:
    """Call :func:`ask_bedrock`, degrading to ``fallback()`` on failure.

    The degradation is counted (``bedrock_heuristic_fallbacks{kind}``) and
    logged at ERROR, so a system silently running on heuristics shows up in
    metrics instead of looking healthy.
    """
    try:
        return ask_bedrock(prompt)
    except BedrockInvocationError as e:
        failure_metrics.record_heuristic_fallback(e.kind)
        logger.error("bedrock degraded to heuristic fallback kind=%s", e.kind)
        return fallback()


def ask_bedrock_json(
    prompt: str,
    *,
    schema: dict[str, Any] | None = None,
    task: str = "standard",
    agent: str = "unknown",
    mission_id: str | None = None,
) -> dict[str, Any]:
    """Structured call: JSON arrives as a parsed dict via forced tool-use.

    There is no text-to-JSON parsing step — the shape is enforced by the
    ``toolChoice`` contract on the Bedrock side. Fails loudly (R6 point 3):
    raises :class:`BedrockInvocationError` rather than returning ``None``.
    """
    text = (prompt or "").strip()
    if not text:
        raise ValueError("ask_bedrock_json called with empty prompt")

    response = _converse(
        prompt=text,
        task=task,
        agent=agent,
        mission_id=mission_id,
        tool_schema=schema or _ANY_OBJECT_SCHEMA,
    )

    for block in _content_blocks(response):
        if not isinstance(block, dict):
            continue
        tool_use = block.get("toolUse")
        if isinstance(tool_use, dict):
            payload = tool_use.get("input")
            if isinstance(payload, dict):
                return payload
    raise _fail("converse returned no structured toolUse block", kind="no_structured_output")
