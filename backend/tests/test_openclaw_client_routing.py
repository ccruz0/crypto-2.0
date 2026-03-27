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


def test_investigation_symptom_fact_gate() -> None:
    # Load module directly so this test runs without full app.services import chain (pydantic_settings, etc.).
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "openclaw_client_symptom",
        root / "app/services/openclaw_client.py",
    )
    assert spec and spec.loader
    oc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oc)
    investigation_symptom_fact_gate_fails = oc.investigation_symptom_fact_gate_fails

    fail, _ = investigation_symptom_fact_gate_fails(
        "Root cause: missing files on the server.",
        has_embedded_excerpts=False,
    )
    assert fail is False

    fail2, reason = investigation_symptom_fact_gate_fails(
        "## Root Cause\nThe issue is missing files in the deployment.",
        has_embedded_excerpts=True,
    )
    assert fail2 is True
    assert "missing files" in reason.lower()

    fail3, _ = investigation_symptom_fact_gate_fails(
        "The reported missing-files hypothesis is unproven; excerpts show files are not missing.",
        has_embedded_excerpts=True,
    )
    assert fail3 is False


def test_investigation_excerpt_fidelity_gate() -> None:
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "openclaw_client_fidelity",
        root / "app/services/openclaw_client.py",
    )
    assert spec and spec.loader
    oc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oc)
    gate = oc.investigation_excerpt_fidelity_gate_fails

    emb = "def real_only():\n    return 1\n"
    bad = (
        "## Root Cause\n\n```python\ndef invented_xyz():\n    pass\n```\n\n"
        "## Recommended Fix\nNew code here.\n"
    )
    fail, reason = gate(bad, emb)
    assert fail is True
    assert "invented_xyz" in reason

    ok_content = (
        "## Root Cause\n\n```python\ndef real_only():\n    return 1\n```\n\n"
        "## Recommended Fix\n```python\ndef brand_new():\n    pass\n```"
    )
    fail2, _ = gate(ok_content, emb)
    assert fail2 is False


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
