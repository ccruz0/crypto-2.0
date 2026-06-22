"""AWS Bedrock implementation of the LLMProvider seam.

Uses boto3 ``bedrock-runtime`` with the Anthropic Claude messages format. boto3
is imported lazily so importing this module (and running tests) never requires
AWS. All vendor errors are wrapped in ``LLMProviderError``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .flags import bedrock_enabled
from .provider import LLMProvider, LLMProviderError, LLMResponse

logger = logging.getLogger(__name__)

# Bedrock-first preferred model (Anthropic Claude). Overridable via env.
_DEFAULT_MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"
_DEFAULT_REGION = "ap-southeast-1"


class BedrockProvider(LLMProvider):
    """Thin Bedrock completion provider. ``client`` is injectable for tests."""

    def __init__(
        self,
        *,
        model_id: str | None = None,
        region: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._model_id = model_id or os.environ.get("JARVIS_BEDROCK_MODEL_ID") or _DEFAULT_MODEL_ID
        self._region = region or os.environ.get("JARVIS_BEDROCK_REGION") or _DEFAULT_REGION
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise LLMProviderError("boto3 not installed") from exc
        try:
            self._client = boto3.client("bedrock-runtime", region_name=self._region)
        except Exception as exc:  # pragma: no cover - environment dependent
            raise LLMProviderError(f"failed to create bedrock-runtime client: {exc}") from exc
        return self._client

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system

        client = self._get_client()
        try:
            resp = client.invoke_model(
                modelId=self._model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            payload = resp.get("body") if isinstance(resp, dict) else None
            raw = payload.read() if hasattr(payload, "read") else payload
            data = json.loads(raw)
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(f"bedrock invoke_model failed: {exc}") from exc

        return LLMResponse(text=_extract_text(data), model_id=self._model_id, raw=data)


def _extract_text(data: dict[str, Any]) -> str:
    """Pull assistant text from an Anthropic-on-Bedrock response body."""
    try:
        parts = data.get("content") or []
        texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text"]
        joined = "\n".join(t for t in texts if t).strip()
        if joined:
            return joined
    except Exception:  # pragma: no cover - defensive
        pass
    return (data.get("completion") or "").strip()


def get_bedrock_provider() -> BedrockProvider:
    """Fail-closed factory: raises unless JARVIS_BEDROCK_ENABLED is truthy."""
    if not bedrock_enabled():
        raise LLMProviderError("Bedrock disabled (JARVIS_BEDROCK_ENABLED is not set)")
    return BedrockProvider()
