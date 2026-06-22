"""Tests for the Bedrock LLM provider seam. boto3 is mocked; no real AWS calls."""

from __future__ import annotations

import io
import json
import sys

import pytest

from app.jarvis.llm.bedrock_provider import BedrockProvider, get_bedrock_provider
from app.jarvis.llm.provider import LLMProvider, LLMProviderError, LLMResponse


class _FakeBody:
    def __init__(self, payload: dict) -> None:
        self._buf = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def read(self) -> bytes:
        return self._buf.read()


class _FakeClient:
    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        self._payload = payload or {"content": [{"type": "text", "text": "hello"}]}
        self._error = error
        self.calls: list[dict] = []

    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return {"body": _FakeBody(self._payload)}


def test_provider_is_subclass_of_interface():
    assert issubclass(BedrockProvider, LLMProvider)


def test_complete_parses_anthropic_text():
    client = _FakeClient({"content": [{"type": "text", "text": "disk is 92% full"}]})
    provider = BedrockProvider(model_id="m-test", region="ap-southeast-1", client=client)
    resp = provider.complete("why is disk full?", system="be brief", max_tokens=100)
    assert isinstance(resp, LLMResponse)
    assert resp.text == "disk is 92% full"
    assert resp.model_id == "m-test"
    # request shape sanity
    body = json.loads(client.calls[0]["body"])
    assert body["messages"][0]["content"] == "why is disk full?"
    assert body["system"] == "be brief"


def test_complete_wraps_vendor_error():
    client = _FakeClient(error=RuntimeError("throttled"))
    provider = BedrockProvider(region="ap-southeast-1", client=client)
    with pytest.raises(LLMProviderError):
        provider.complete("x")


def test_factory_fail_closed_when_flag_off(monkeypatch):
    monkeypatch.delenv("JARVIS_BEDROCK_ENABLED", raising=False)
    with pytest.raises(LLMProviderError):
        get_bedrock_provider()


def test_factory_returns_provider_when_flag_on(monkeypatch):
    monkeypatch.setenv("JARVIS_BEDROCK_ENABLED", "true")
    monkeypatch.setenv("JARVIS_BEDROCK_REGION", "ap-southeast-1")
    provider = get_bedrock_provider()
    assert isinstance(provider, BedrockProvider)


def test_region_from_env_is_used(monkeypatch):
    # With JARVIS_BEDROCK_REGION set, that region must reach boto3.client(...).
    monkeypatch.setenv("JARVIS_BEDROCK_REGION", "ap-southeast-1")
    captured: dict = {}

    class _FakeBoto3:
        def client(self, name, **kwargs):
            captured["name"] = name
            captured["region_name"] = kwargs.get("region_name")
            return _FakeClient()

    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3())
    provider = BedrockProvider()
    provider.complete("why is disk full?")

    assert captured["name"] == "bedrock-runtime"
    assert captured["region_name"] == "ap-southeast-1"


def test_constructor_region_arg_takes_precedence(monkeypatch):
    monkeypatch.delenv("JARVIS_BEDROCK_REGION", raising=False)
    provider = BedrockProvider(region="ap-southeast-1", client=_FakeClient())
    assert provider._region == "ap-southeast-1"


def test_construction_fails_closed_when_region_unset(monkeypatch):
    monkeypatch.delenv("JARVIS_BEDROCK_REGION", raising=False)
    with pytest.raises(LLMProviderError, match="JARVIS_BEDROCK_REGION"):
        BedrockProvider()


def test_factory_fails_closed_when_region_unset(monkeypatch):
    # Flag on, but region unset: must fail closed, not silently pick a region.
    monkeypatch.setenv("JARVIS_BEDROCK_ENABLED", "true")
    monkeypatch.delenv("JARVIS_BEDROCK_REGION", raising=False)
    with pytest.raises(LLMProviderError, match="JARVIS_BEDROCK_REGION"):
        get_bedrock_provider()
