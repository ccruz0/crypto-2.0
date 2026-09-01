"""Issue #626: human promote API + pending quality gate."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _seed_candidate(tmp_path: Path, *, version: int = 5, metric: float = 0.85) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "candidate.joblib").write_bytes(b"fake-model")
    candidate = {
        "version": version,
        "n_fit_rows": 40,
        "metrics": {"holdout": True, "roc_auc": metric, "accuracy": 0.8},
        "dataset_meta": {
            "label_source": "hybrid",
            "n_from_trade_outcome": 12,
            "n_from_alert": 30,
            "n_trade_outcome_long": 7,
            "n_trade_outcome_short": 5,
        },
    }
    (tmp_path / "candidate_manifest.json").write_text(
        json.dumps(candidate, indent=2) + "\n", encoding="utf-8"
    )
    current = {
        "version": 4,
        "n_fit_rows": 35,
        "metrics": {"holdout": True, "roc_auc": 0.7, "accuracy": 0.65},
        "dataset_meta": candidate["dataset_meta"],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    (tmp_path / "current.joblib").write_bytes(b"old-model")


def test_merit_only_passes_without_human_flag(monkeypatch):
    monkeypatch.delenv("AUTO_ML_HUMAN_PROMOTE", raising=False)
    monkeypatch.delenv("AUTO_ML_AUTONOMOUS_PROMOTE", raising=False)
    from app.services.auto_entry_promote import should_promote

    cand = {"n_fit_rows": 30, "metrics": {"holdout": True, "roc_auc": 0.9}}
    cur = {"n_fit_rows": 30, "metrics": {"holdout": True, "roc_auc": 0.6}}
    quality = should_promote(cand, cur, merit_only=True)
    permission = should_promote(cand, cur, merit_only=False)
    assert quality.should_promote is True
    assert permission.should_promote is False
    assert permission.reason == "autonomous_promote_disabled"


def test_write_and_load_pending_promote(tmp_path: Path):
    from app.services.auto_entry_promote import (
        PromoteDecision,
        load_pending_promote,
        write_pending_promote,
    )

    candidate = {"version": 9, "n_fit_rows": 25}
    decision = PromoteDecision(
        should_promote=True,
        reason="metric_improved:0.6000->0.8000(delta>=0.0)",
        candidate_metric=0.8,
        current_metric=0.6,
        min_rows=20,
        min_delta=0.0,
        autonomous=False,
        human_promote=False,
    )
    payload = write_pending_promote(tmp_path, candidate=candidate, decision=decision)
    assert payload["quality_gate_passed"] is True
    loaded = load_pending_promote(tmp_path)
    assert loaded is not None
    assert loaded["candidate_version"] == 9


def test_promote_candidate_from_disk_with_human_gate(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AUTO_ML_HUMAN_PROMOTE", "true")
    monkeypatch.delenv("AUTO_ML_AUTONOMOUS_PROMOTE", raising=False)
    _seed_candidate(tmp_path)

    from app.services.auto_entry_promote import promote_candidate_from_disk

    result = promote_candidate_from_disk(tmp_path, human=True, send_telegram=False)
    assert result["ok"] is True
    assert result["promoted"] is True
    assert (tmp_path / "current.joblib").read_bytes() == b"fake-model"
    assert not (tmp_path / "pending_promote.json").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["version"] == 5
    assert manifest["human_promote"] is True
    assert manifest["autonomous_promote"] is False


def test_post_auto_ml_promote_route(tmp_path: Path, monkeypatch):
    model_path = tmp_path / "current.joblib"
    _seed_candidate(tmp_path)
    monkeypatch.setenv("AUTO_ML_MODEL_PATH", str(model_path))
    monkeypatch.setenv("AUTO_ML_HUMAN_PROMOTE", "true")
    monkeypatch.delenv("AUTO_ML_AUTONOMOUS_PROMOTE", raising=False)

    from app.routers.config import router
    from app.services.auto_entry_model import reset_model_cache

    reset_model_cache()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    missing = client.post("/api/config/auto-ml/promote", json={})
    assert missing.status_code == 400

    res = client.post("/api/config/auto-ml/promote", json={"confirm": True, "telegram": False})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["promoted_manifest"]["version"] == 5
    assert body["status"]["human_promote"] is True
    assert body["status"]["pending_promote"] is False


def test_get_auto_ml_status_includes_pending_and_long_short(tmp_path: Path, monkeypatch):
    model_path = tmp_path / "current.joblib"
    _seed_candidate(tmp_path)
    monkeypatch.setenv("AUTO_ML_MODEL_PATH", str(model_path))

    from app.services.auto_entry_promote import PromoteDecision, write_pending_promote
    from app.services.auto_entry_model import get_auto_ml_status, reset_model_cache

    candidate = json.loads((tmp_path / "candidate_manifest.json").read_text())
    write_pending_promote(
        tmp_path,
        candidate=candidate,
        decision=PromoteDecision(
            should_promote=True,
            reason="metric_improved:0.7000->0.8500(delta>=0.0)",
            candidate_metric=0.85,
            current_metric=0.7,
            min_rows=20,
            min_delta=0.0,
            autonomous=False,
            human_promote=False,
        ),
    )

    reset_model_cache()
    status = get_auto_ml_status()
    assert status["pending_promote"] is True
    assert status["candidate_version"] == 5
    assert status["n_trade_outcome_long"] == 7
    assert status["n_trade_outcome_short"] == 5
    assert status["candidate_n_trade_outcome_short"] == 5
