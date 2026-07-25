"""Offline Auto ML feature/label/train tests (PR-ML-A). No live gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from auto_ml_features import (  # noqa: E402
    FEATURE_NAMES,
    attach_features_and_label,
    derive_label,
    extract_features,
    feature_vector,
)
from build_auto_ml_dataset import build_rich_demo_alerts  # noqa: E402
from eval_alert_quality import evaluate_alerts  # noqa: E402


def test_extract_features_order_and_side():
    feats = extract_features(
        side="BUY",
        entry_price=100.0,
        entry_ts_ms=1_700_000_000_000,
        context={
            "rsi": 28,
            "ma50": 98,
            "ma200": 90,
            "ema10": 99,
            "volume_ratio": 1.5,
            "atr": 2.0,
            "strategy_index": 80,
        },
    )
    assert feats["rsi"] == pytest.approx(28.0)
    assert feats["ma50_dist"] == pytest.approx(0.02)
    assert feats["side_buy"] == 1.0
    vec = feature_vector(feats)
    assert len(vec) == len(FEATURE_NAMES)
    assert vec[0] == pytest.approx(28.0)


def test_derive_label_rules():
    assert derive_label({"dir_acc_1h": True, "tp_before_sl": False}) == 1
    assert derive_label({"dir_acc_1h": False, "tp_before_sl": True}) == 1
    assert derive_label({"dir_acc_1h": False, "tp_before_sl": False}) == 0
    assert derive_label({"dir_acc_1h": None, "tp_before_sl": None}) is None
    assert derive_label({"error": "boom", "dir_acc_1h": True}) is None


def test_dataset_from_demo_fixture():
    alerts = build_rich_demo_alerts()
    labeled, summary = evaluate_alerts(alerts, fixture_candles=True)
    assert summary["n_labeled"] >= 1
    raw_by_id = {a["id"]: a for a in alerts}
    for row in labeled:
        raw = raw_by_id.get(row.get("id"))
        if raw:
            row["context_json"] = raw.get("context_json")
    dataset = attach_features_and_label(labeled, raw_by_id=raw_by_id)
    assert len(dataset) >= 4
    assert all(len(r["x"]) == len(FEATURE_NAMES) for r in dataset)
    assert all(r["y"] in (0, 1) for r in dataset)
    assert sum(r["y"] for r in dataset) >= 1
    assert sum(1 for r in dataset if r["y"] == 0) >= 1


def test_train_script_on_demo(tmp_path, monkeypatch):
    pytest.importorskip("sklearn")
    pytest.importorskip("joblib")

    # Build dataset into tmp
    from build_auto_ml_dataset import main as build_main
    from train_auto_entry_model import main as train_main

    ds = tmp_path / "dataset.json"
    out_dir = tmp_path / "models"
    rc = build_main(["--demo", "--out", str(ds)])
    assert rc == 0
    payload = json.loads(ds.read_text())
    assert payload["meta"]["n_dataset_rows"] >= 4

    rc = train_main(
        ["--dataset", str(ds), "--out-dir", str(out_dir), "--min-rows", "4", "--test-size", "0.25"]
    )
    assert rc == 0
    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "current.joblib").exists()
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["live_gate_enabled"] is False
    assert manifest["feature_version"] == 1
    assert manifest["version"] == 1
