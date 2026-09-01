"""Offline tests for R6 point 3: fail-loud ask_bedrock + counted fallback.

No AWS is required: a fake ``boto3`` / ``botocore.exceptions`` pair is injected
into ``sys.modules`` for the duration of each test.
"""

from __future__ import annotations

import sys
import types

import pytest

from app.jarvis import failure_metrics
from app.jarvis.bedrock_client import (
    BedrockInvocationError,
    ask_bedrock,
    ask_bedrock_with_fallback,
)


class _FakeClientError(Exception):
    """Mimics botocore ClientError: carries the ``response`` dict boto3 sets."""

    def __init__(self, message: str, code: str = "ValidationException") -> None:
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message}}


class _FakeBotoCoreError(Exception):
    pass


def _text_response(text: str) -> dict:
    """Shape of a converse() reply carrying assistant text."""
    return {
        "output": {"message": {"content": [{"text": text}] if text else []}},
        "usage": {"inputTokens": 1, "outputTokens": 1},
    }


def _install_fake_boto3(monkeypatch, *, invoke):
    """Install a fake boto3 whose converse() delegates to ``invoke``."""
    botocore_exc = types.ModuleType("botocore.exceptions")
    botocore_exc.ClientError = _FakeClientError
    botocore_exc.BotoCoreError = _FakeBotoCoreError
    botocore_pkg = types.ModuleType("botocore")
    botocore_pkg.exceptions = botocore_exc

    class _FakeClient:
        def converse(self, **kwargs):
            return invoke(**kwargs)

    boto3_mod = types.ModuleType("boto3")
    boto3_mod.client = lambda *a, **k: _FakeClient()

    monkeypatch.setitem(sys.modules, "boto3", boto3_mod)
    monkeypatch.setitem(sys.modules, "botocore", botocore_pkg)
    monkeypatch.setitem(sys.modules, "botocore.exceptions", botocore_exc)


@pytest.fixture(autouse=True)
def _clean_metrics():
    failure_metrics.reset()
    yield
    failure_metrics.reset()


def test_success_returns_text_and_counts_no_failure(monkeypatch):
    def invoke(**kwargs):
        return _text_response("hello world")

    _install_fake_boto3(monkeypatch, invoke=invoke)
    assert ask_bedrock("hi") == "hello world"
    assert failure_metrics.snapshot() == {}


def test_empty_prompt_raises_value_error(monkeypatch):
    with pytest.raises(ValueError):
        ask_bedrock("   ")


def test_client_error_raises_and_counts_with_kind(monkeypatch):
    def invoke(**kwargs):
        raise _FakeClientError(
            "An error occurred (ValidationException) when calling the "
            "InvokeModel operation: Operation not allowed"
        )

    _install_fake_boto3(monkeypatch, invoke=invoke)
    with pytest.raises(BedrockInvocationError) as ei:
        ask_bedrock("hi")
    assert ei.value.kind == "account_restriction"
    assert failure_metrics.snapshot() == {
        "bedrock_invocation_failures[account_restriction]": 1
    }


def test_model_not_found_kind(monkeypatch):
    def invoke(**kwargs):
        raise _FakeClientError(
            "An error occurred (ResourceNotFoundException): could not resolve "
            "the foundation model",
            code="ResourceNotFoundException",
        )

    _install_fake_boto3(monkeypatch, invoke=invoke)
    with pytest.raises(BedrockInvocationError) as ei:
        ask_bedrock("hi")
    assert ei.value.kind == "model_not_found"


def test_no_assistant_text_is_a_failure(monkeypatch):
    def invoke(**kwargs):
        return _text_response("")

    _install_fake_boto3(monkeypatch, invoke=invoke)
    with pytest.raises(BedrockInvocationError) as ei:
        ask_bedrock("hi")
    assert ei.value.kind == "no_assistant_text"


def test_fallback_returns_heuristic_and_counts_fallback(monkeypatch):
    def invoke(**kwargs):
        raise _FakeClientError(
            "An error occurred (ValidationException): Operation not allowed"
        )

    _install_fake_boto3(monkeypatch, invoke=invoke)
    result = ask_bedrock_with_fallback("hi", lambda: "HEURISTIC")
    assert result == "HEURISTIC"
    snap = failure_metrics.snapshot()
    # Both the underlying failure and the fallback are counted, labelled by kind.
    assert snap["bedrock_invocation_failures[account_restriction]"] == 1
    assert snap["bedrock_heuristic_fallbacks[account_restriction]"] == 1


def test_fallback_passes_through_success(monkeypatch):
    def invoke(**kwargs):
        return _text_response("ok")

    _install_fake_boto3(monkeypatch, invoke=invoke)
    assert ask_bedrock_with_fallback("hi", lambda: "HEURISTIC") == "ok"
    assert failure_metrics.snapshot() == {}
