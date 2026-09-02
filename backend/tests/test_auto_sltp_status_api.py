"""Phase 2 Auto ML SL/TP status + promote API tests (#623)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _seed_candidate(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    candidate = {
        "version": 2,
        "n_fit_rows": 20,
        "n_holdout_rows": 5,
        "sl_pct": 2.5,
        "tp_pct": 4.0,
        "metrics": {
            "holdout": {"n": 5, "expectancy_pct": 0.5},
            "baseline_holdout": {"n": 5, "expectancy_pct": 0.3},
            "merit_delta_expectancy": 0.2,
        },
    }
    (tmp_path / "sltp_candidate_manifest.json").write_text(
        json.dumps(candidate, indent=2) + "\n", encoding="utf-8"
    )


def test_get_auto_ml_sltp_status_endpoint(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTO_ML_SLTP_DIR", str(tmp_path))
    from app.routers.config import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/api/config/auto-ml/sltp")
    assert resp.status_code == 200
    body = resp.json()
    assert "gate_enabled" in body
    assert body["manifest_present"] is False


def test_post_auto_ml_sltp_promote_human_gate(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTO_ML_SLTP_DIR", str(tmp_path))
    _seed_candidate(tmp_path)
    from app.routers.config import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.post("/api/config/auto-ml/sltp/promote", json={"confirm": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert (tmp_path / "sltp_manifest.json").is_file()
