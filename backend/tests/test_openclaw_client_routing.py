"""Tests for OpenClaw cost-routing helpers (cheap chain, prompt truncation)."""

from __future__ import annotations

import pytest


@pytest.fixture
def clear_openclaw_cost_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove cost-related env vars so each test sets exactly what it needs."""
    for key in (
        "OPENCLAW_CHEAP_MODEL_CHAIN",
        "OPENCLAW_CHEAP_PRIMARY_MODEL",
        "OPENCLAW_CHEAP_TASK_TYPES",
        "OPENCLAW_TASK_DETAILS_MAX_CHARS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_get_apply_model_chain_subdir_when_task_types_empty(
    monkeypatch: pytest.MonkeyPatch,
    clear_openclaw_cost_env: None,
) -> None:
    monkeypatch.setenv("OPENCLAW_CHEAP_MODEL_CHAIN", "openai/gpt-4o-mini")
    from app.services import openclaw_client as oc

    prepared = {"task": {"type": "documentation", "id": "p1"}}
    assert oc.get_apply_model_chain_override(prepared, "docs/agents/generated-notes") == [
        "openai/gpt-4o-mini",
    ]
    assert oc.get_apply_model_chain_override(prepared, "docs/runbooks/triage") == [
        "openai/gpt-4o-mini",
    ]
    assert oc.get_apply_model_chain_override(prepared, "docs/agents/bug-investigations") is None


def test_get_apply_model_chain_matches_type_when_types_set(
    monkeypatch: pytest.MonkeyPatch,
    clear_openclaw_cost_env: None,
) -> None:
    monkeypatch.setenv("OPENCLAW_CHEAP_MODEL_CHAIN", "cheap/model")
    monkeypatch.setenv("OPENCLAW_CHEAP_TASK_TYPES", "doc,monitoring")
    from app.services import openclaw_client as oc

    prepared = {"task": {"type": "doc", "id": "p2"}}
    assert oc.get_apply_model_chain_override(prepared, "some/other/path") == ["cheap/model"]


def test_get_apply_model_chain_no_match_when_types_set_and_wrong_subdir(
    monkeypatch: pytest.MonkeyPatch,
    clear_openclaw_cost_env: None,
) -> None:
    monkeypatch.setenv("OPENCLAW_CHEAP_MODEL_CHAIN", "cheap/model")
    monkeypatch.setenv("OPENCLAW_CHEAP_TASK_TYPES", "doc")
    from app.services import openclaw_client as oc

    prepared = {"task": {"type": "bug", "id": "p3"}}
    assert oc.get_apply_model_chain_override(prepared, "unrelated/path") is None


def test_truncate_task_text_default_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCLAW_TASK_DETAILS_MAX_CHARS", raising=False)
    from app.services import openclaw_client as oc

    long = "x" * 9000
    out = oc._truncate_task_text(long)
    assert len(out) < len(long)
    assert "truncated" in out.lower()


def test_task_metadata_truncates_details() -> None:
    from app.services.openclaw_client import _task_metadata_block

    prepared = {
        "task": {
            "task": "Title",
            "id": "id",
            "type": "Bug",
            "details": "D" * 12000,
        },
        "repo_area": {},
    }
    meta = _task_metadata_block(prepared)
    assert "truncated" in meta.lower()
    assert meta.count("D") < 12000


def test_post_one_includes_max_output_tokens_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCLAW_API_TOKEN", "test-token")
    monkeypatch.setenv("OPENCLAW_API_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("OPENCLAW_MAX_OUTPUT_TOKENS", "4096")
    from unittest.mock import MagicMock, patch

    from app.services import openclaw_client as oc

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"output": []}

    with patch("httpx.Client") as client_cls:
        mock_client = MagicMock()
        client_cls.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        oc._post_one("hi", "m1", task_id="t1")

    call_kw = mock_client.post.call_args
    body = call_kw[1]["json"]
    assert body.get("max_output_tokens") == 4096


def test_post_one_treats_openresponses_failed_envelope_as_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP 200 with JSON status=failed must not be treated as success (defensive)."""
    monkeypatch.setenv("OPENCLAW_API_TOKEN", "test-token")
    monkeypatch.setenv("OPENCLAW_API_URL", "http://127.0.0.1:9")
    from unittest.mock import MagicMock, patch

    from app.services import openclaw_client as oc

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "failed",
        "model": "openai/gpt-4o-mini",
        "output": [],
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "error": {"code": "api_error", "message": "internal error"},
    }

    with patch("httpx.Client") as client_cls:
        mock_client = MagicMock()
        client_cls.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        out = oc._post_one("hi", "openai/gpt-4o-mini", task_id="t-fail")

    assert out.get("success") is False
    assert "status=failed" in (out.get("error") or "")
    assert "internal error" in (out.get("error") or "")
