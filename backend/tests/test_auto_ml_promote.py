"""PR-ML-C: retrain promote decision tests."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.auto_entry_promote import (
    apply_promote,
    primary_metric,
    should_promote,
)


def test_format_promote_telegram_includes_changes_and_why():
    from app.services.auto_entry_promote import PromoteDecision, format_promote_telegram

    decision = PromoteDecision(
        should_promote=True,
        reason="metric_improved:0.6000->0.8000(delta>=0.0)",
        candidate_metric=0.8,
        current_metric=0.6,
        min_rows=10,
        min_delta=0.0,
        autonomous=True,
    )
    prev = {
        "version": 1,
        "metrics": {"holdout": True, "roc_auc": 0.6, "accuracy": 0.55},
        "n_fit_rows": 10,
    }
    promoted = {
        "version": 2,
        "promoted_at": "2026-07-25T02:00:00+00:00",
        "n_fit_rows": 20,
        "live_gate_enabled": True,
        "feature_version": 1,
        "metrics": {"holdout": True, "roc_auc": 0.8, "accuracy": 0.75},
        "dataset_meta": {"source": "api:demo", "n_positive": 12, "n_negative": 8},
    }
    msg = format_promote_telegram(promoted, decision, previous=prev)
    assert "NUEVA VERSIÓN" in msg
    assert "v1 → v2" in msg
    assert "Por qué:" in msg
    assert "Cambios aplicados:" in msg
    assert "0.6000" in msg and "0.8000" in msg
    assert "mejoró la métrica" in msg.lower() or "holdout" in msg.lower()


def test_should_promote_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AUTO_ML_AUTONOMOUS_PROMOTE", raising=False)
    monkeypatch.delenv("AUTO_ML_HUMAN_PROMOTE", raising=False)
    cand = {
        "n_fit_rows": 50,
        "metrics": {"holdout": True, "roc_auc": 0.9, "accuracy": 0.8},
    }
    d = should_promote(cand, None)
    assert d.should_promote is False
    assert d.reason == "autonomous_promote_disabled"
    assert d.human_promote is False
    quality = should_promote(cand, None, merit_only=True)
    assert quality.should_promote is True
    assert quality.reason == "no_current_baseline"


def test_should_promote_with_human_gate_without_autonomous(monkeypatch):
    monkeypatch.delenv("AUTO_ML_AUTONOMOUS_PROMOTE", raising=False)
    monkeypatch.setenv("AUTO_ML_HUMAN_PROMOTE", "true")
    monkeypatch.setenv("AUTO_ML_PROMOTE_MIN_ROWS", "10")
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
    assert d.autonomous is False
    assert d.human_promote is True
    assert "metric_improved" in d.reason


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


def test_send_promote_telegram_uses_http_client(monkeypatch):
    from app.services import auto_entry_promote as mod

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_AWS", "token-test")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_AWS", "chat-test")
    calls = {}

    class _Resp:
        status_code = 200

    def fake_http_post(url, json=None, timeout=10, calling_module="unknown", **kwargs):
        calls["url"] = url
        calls["json"] = json
        calls["calling_module"] = calling_module
        calls["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr("app.utils.http_client.http_post", fake_http_post)
    assert mod.send_promote_telegram("<b>hi</b>") is True
    assert "api.telegram.org/bottoken-test/sendMessage" in calls["url"]
    assert calls["json"]["chat_id"] == "chat-test"
    assert calls["json"]["text"] == "<b>hi</b>"
    assert calls["calling_module"] == "auto_entry_promote.send_promote_telegram"
