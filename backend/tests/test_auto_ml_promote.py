"""PR-ML-C: retrain promote decision tests."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.auto_entry_promote import (
    apply_promote,
    primary_metric,
    should_promote,
)


def test_primary_metric_prefers_auc():
    assert primary_metric({"holdout": True, "roc_auc": 0.7, "accuracy": 0.5}) == 0.7
    assert primary_metric({"holdout": True, "roc_auc": None, "accuracy": 0.6}) == 0.6
    assert primary_metric({"holdout": False, "note": "single_class_fit_on_all", "accuracy": 1.0}) is None


def test_should_promote_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AUTO_ML_AUTONOMOUS_PROMOTE", raising=False)
    cand = {
        "n_fit_rows": 50,
        "metrics": {"holdout": True, "roc_auc": 0.9, "accuracy": 0.8},
    }
    d = should_promote(cand, None)
    assert d.should_promote is False
    assert d.reason == "autonomous_promote_disabled"


def test_should_promote_when_autonomous_and_better(monkeypatch):
    monkeypatch.setenv("AUTO_ML_AUTONOMOUS_PROMOTE", "true")
    monkeypatch.setenv("AUTO_ML_PROMOTE_MIN_ROWS", "10")
    monkeypatch.setenv("AUTO_ML_PROMOTE_MIN_DELTA", "0.0")
    cand = {
        "n_fit_rows": 20,
        "metrics": {"holdout": True, "roc_auc": 0.8, "accuracy": 0.75},
    }
    cur = {
        "n_fit_rows": 20,
        "metrics": {"holdout": True, "roc_auc": 0.6, "accuracy": 0.55},
    }
    d = should_promote(cand, cur)
    assert d.should_promote is True
    assert "metric_improved" in d.reason


def test_should_not_promote_when_worse(monkeypatch):
    monkeypatch.setenv("AUTO_ML_AUTONOMOUS_PROMOTE", "true")
    monkeypatch.setenv("AUTO_ML_PROMOTE_MIN_ROWS", "5")
    cand = {"n_fit_rows": 10, "metrics": {"holdout": True, "roc_auc": 0.4}}
    cur = {"n_fit_rows": 10, "metrics": {"holdout": True, "roc_auc": 0.7}}
    d = should_promote(cand, cur)
    assert d.should_promote is False
    assert "metric_not_improved" in d.reason


def test_apply_promote_writes_current(tmp_path: Path):
    cand_model = tmp_path / "candidate.joblib"
    cand_model.write_bytes(b"fake-model")
    cand_manifest = {
        "version": 3,
        "model_file": "auto_entry_v3.joblib",
        "n_fit_rows": 12,
        "metrics": {"holdout": True, "roc_auc": 0.7},
    }
    from app.services.auto_entry_promote import PromoteDecision

    decision = PromoteDecision(
        should_promote=True,
        reason="force",
        candidate_metric=0.7,
        current_metric=None,
        min_rows=1,
        min_delta=0.0,
        autonomous=True,
    )
    promoted = apply_promote(
        tmp_path,
        candidate_model=cand_model,
        candidate_manifest=cand_manifest,
        decision=decision,
    )
    assert (tmp_path / "current.joblib").is_file()
    assert (tmp_path / "manifest.json").is_file()
    assert promoted["version"] == 3
    assert promoted["autonomous_promote"] is True
    man = json.loads((tmp_path / "manifest.json").read_text())
    assert man["promote_reason"] == "force"
