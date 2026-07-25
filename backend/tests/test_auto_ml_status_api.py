"""PR-ML-D: Auto ML status API."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_get_auto_ml_status_shape(monkeypatch):
    monkeypatch.delenv("AUTO_ML_ENABLED", raising=False)
    monkeypatch.delenv("AUTO_ML_AUTONOMOUS_PROMOTE", raising=False)
    monkeypatch.setenv("AUTO_ML_MODEL_PATH", "/tmp/does-not-exist-auto-ml.joblib")

    from app.services.auto_entry_model import get_auto_ml_status, reset_model_cache

    reset_model_cache()
    status = get_auto_ml_status()
    assert status["gate_enabled"] is False
    assert status["autonomous_promote"] is False
    assert status["model_present"] is False
    assert "threshold" in status
    assert "feature_version" in status
    assert isinstance(status["feature_names"], list)


def test_auto_ml_route(monkeypatch):
    monkeypatch.delenv("AUTO_ML_ENABLED", raising=False)
    monkeypatch.setenv("AUTO_ML_MODEL_PATH", "/tmp/does-not-exist-auto-ml.joblib")

    from app.routers.config import router
    from app.services.auto_entry_model import reset_model_cache

    reset_model_cache()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    res = client.get("/api/config/auto-ml")
    assert res.status_code == 200
    body = res.json()
    assert body["gate_enabled"] is False
    assert "model_present" in body
    assert "threshold" in body
