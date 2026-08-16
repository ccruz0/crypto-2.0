"""Offline tests for R6 point 2: config-driven router + Converse-probe preflight."""

from __future__ import annotations

import json

import pytest

from app.jarvis import failure_metrics
from app.jarvis.bedrock_preflight import (
    STATUS_ACCOUNT_RESTRICTED,
    STATUS_MODEL_INVALID,
    STATUS_OK,
    ModelConfigError,
    ModelRouter,
    load_model_config,
)

GOOD = {
    "region": "ap-southeast-1",
    "tiers": {
        "simple": {"id": "global.anthropic.claude-haiku-4-5-20251001-v1:0"},
        "standard": {"id": "global.anthropic.claude-sonnet-4-5-20250929-v1:0"},
        "critical": {"id": "global.anthropic.claude-opus-4-5-20251101-v1:0"},
    },
}


def _write(tmp_path, data) -> str:
    p = tmp_path / "bedrock_models.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


@pytest.fixture(autouse=True)
def _clean_metrics():
    failure_metrics.reset()
    yield
    failure_metrics.reset()


# --- config loading ---------------------------------------------------------

def test_load_and_resolve(tmp_path):
    r = ModelRouter(load_model_config(_write(tmp_path, GOOD)))
    assert r.region == "ap-southeast-1"
    assert r.resolve("simple").endswith("haiku-4-5-20251001-v1:0")
    assert "sonnet-4-5" in r.resolve("standard")
    assert "opus-4-5" in r.resolve("critical")


def test_missing_file():
    with pytest.raises(ModelConfigError, match="not found"):
        load_model_config("/no/such/config.json")


def test_placeholder_ids_rejected(tmp_path):
    bad = json.loads(json.dumps(GOOD))
    bad["tiers"]["standard"]["id"] = "REPLACE_WITH_SONNET_PROFILE_ID"
    with pytest.raises(ModelConfigError, match="placeholder"):
        load_model_config(_write(tmp_path, bad))


def test_missing_tier_rejected(tmp_path):
    bad = json.loads(json.dumps(GOOD))
    del bad["tiers"]["critical"]
    with pytest.raises(ModelConfigError, match="critical"):
        load_model_config(_write(tmp_path, bad))


def test_unknown_tier_raises(tmp_path):
    r = ModelRouter(load_model_config(_write(tmp_path, GOOD)))
    with pytest.raises(ModelConfigError, match="unknown tier"):
        r.resolve("gigantic")


# --- preflight: Converse probe ----------------------------------------------

def _router(tmp_path):
    return ModelRouter(load_model_config(_write(tmp_path, GOOD)))


def test_preflight_all_ok(tmp_path):
    r = _router(tmp_path)
    results = r.preflight(prober=lambda mid: None)  # every probe succeeds
    assert {t: p.status for t, p in results.items()} == {
        "simple": STATUS_OK,
        "standard": STATUS_OK,
        "critical": STATUS_OK,
    }


def test_preflight_hard_fails_on_eol_model(tmp_path):
    r = _router(tmp_path)
    bad_id = GOOD["tiers"]["critical"]["id"]

    def prober(mid):
        if mid == bad_id:
            raise RuntimeError(
                "An error occurred (ResourceNotFoundException): could not resolve "
                "the foundation model"
            )

    with pytest.raises(ModelConfigError) as ei:
        r.preflight(prober=prober)
    msg = str(ei.value)
    assert "preflight failed" in msg
    assert "critical=" in msg
    assert "model_invalid" in msg


def test_preflight_account_restriction_does_not_fail(tmp_path):
    """Every tier blocked by 'Operation not allowed' -> reported, counted, NOT raised.

    This is the current AWS state; the same config must pass once access is enabled.
    """
    r = _router(tmp_path)

    def prober(mid):
        raise RuntimeError(
            "An error occurred (ValidationException) when calling the Converse "
            "operation: Operation not allowed"
        )

    results = r.preflight(prober=prober)  # must NOT raise
    assert all(p.status == STATUS_ACCOUNT_RESTRICTED for p in results.values())
    # Each restricted tier is counted so an alert can fire.
    assert failure_metrics.snapshot()["bedrock_invocation_failures[account_restriction]"] == 3


def test_preflight_catalog_precheck_flags_unlisted_id(tmp_path):
    r = _router(tmp_path)
    # Catalog is missing the critical (opus) profile entirely.
    catalog = [
        GOOD["tiers"]["simple"]["id"],
        GOOD["tiers"]["standard"]["id"],
    ]
    probed = []

    def prober(mid):
        probed.append(mid)  # should never be called for the unlisted id

    with pytest.raises(ModelConfigError) as ei:
        r.preflight(prober=prober, catalog=catalog)
    assert "critical=" in str(ei.value)
    assert GOOD["tiers"]["critical"]["id"] not in probed  # skipped the Converse call


def test_preflight_mixed_invalid_wins_over_restricted(tmp_path):
    r = _router(tmp_path)
    bad_id = GOOD["tiers"]["standard"]["id"]

    def prober(mid):
        if mid == bad_id:
            raise RuntimeError("ResourceNotFoundException: could not resolve the foundation model")
        raise RuntimeError("ValidationException: Operation not allowed")

    # A genuine invalid ID must still fail the preflight even amid restriction noise.
    with pytest.raises(ModelConfigError, match="standard="):
        r.preflight(prober=prober)
