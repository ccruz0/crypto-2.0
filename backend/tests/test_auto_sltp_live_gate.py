"""Phase 2 Auto ML SL/TP live gate tests (#623)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.services.auto_sltp_model import (
    get_auto_sltp_status,
    reset_sltp_cache,
    resolve_effective_sltp_percentages,
)


def test_resolve_effective_sltp_default_off(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("AUTO_ML_SLTP_ENABLED", raising=False)
    monkeypatch.setenv("AUTO_ML_SLTP_DIR", str(tmp_path))
    manifest = {"version": 1, "sl_pct": 2.5, "tp_pct": 4.5}
    (tmp_path / "sltp_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    reset_sltp_cache()

    wl = SimpleNamespace(sl_tp_mode="conservative", sl_percentage=None, tp_percentage=None)
    sl, tp, mode, meta = resolve_effective_sltp_percentages("BTC_USDT", wl)
    assert sl == 3.0
    assert tp == 3.0
    assert meta["auto_sltp_applied"] is False


def test_resolve_effective_sltp_applies_when_gate_on(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTO_ML_SLTP_ENABLED", "true")
    monkeypatch.setenv("AUTO_ML_SLTP_SHADOW_LOG", "false")
    monkeypatch.setenv("AUTO_ML_SLTP_DIR", str(tmp_path))
    (tmp_path / "sltp_manifest.json").write_text(
        json.dumps({"version": 3, "sl_pct": 2.0, "tp_pct": 5.0}), encoding="utf-8"
    )
    reset_sltp_cache()

    monkeypatch.setattr(
        "app.services.auto_sltp_model._coin_preset",
        lambda _sym: "auto",
    )
    wl = SimpleNamespace(sl_tp_mode="conservative", sl_percentage=None, tp_percentage=None)
    sl, tp, _mode, meta = resolve_effective_sltp_percentages("ETH_USDT", wl)
    assert sl == 2.0
    assert tp == 5.0
    assert meta["auto_sltp_applied"] is True
    assert meta["source"] == "auto_ml_sltp"


def test_get_auto_sltp_status_reads_manifest(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTO_ML_SLTP_DIR", str(tmp_path))
    (tmp_path / "sltp_manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sl_pct": 2.5,
                "tp_pct": 4.0,
                "n_fit_rows": 18,
                "n_holdout_rows": 5,
                "metrics": {"merit_delta_expectancy": 0.04},
                "dataset_meta": {"n_complete": 23, "n_long": 15, "n_short": 8},
            }
        ),
        encoding="utf-8",
    )
    reset_sltp_cache()
    status = get_auto_sltp_status()
    assert status["manifest_present"] is True
    assert status["sl_pct"] == 2.5
    assert status["n_long"] == 15
    assert status["gate_enabled"] is False
