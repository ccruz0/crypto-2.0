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
    TRADE_OUTCOME_LABEL_DEF,
    attach_features_and_label,
    attach_features_from_trade_outcomes,
    derive_label,
    extract_features,
    feature_vector,
    merge_alert_and_trade_datasets,
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


def _rich_outcome(**overrides):
    base = {
        "telegram_message_id": 101,
        "symbol": "DOGE_USD",
        "side": "SELL",
        "entry_price": 0.07,
        "entry_ts": "2026-08-01T12:00:00+00:00",
        "label": 1,
        "pnl_usd": 12.5,
        "exit_reason": "TAKE_PROFIT",
        "entry_exchange_order_id": "entry-1",
        "context_json": {
            "entry_price": 0.07,
            "rsi": 72,
            "ma50": 0.068,
            "ma200": 0.06,
            "ema10": 0.069,
            "volume_ratio": 1.2,
            "atr": 0.001,
            "strategy_index": 70,
        },
    }
    base.update(overrides)
    return base


def test_trade_outcome_win_to_dataset_row():
    rows, suppress = attach_features_from_trade_outcomes(
        [_rich_outcome(label=1, pnl_usd=5.0)]
    )
    assert len(rows) == 1
    assert suppress == set()
    assert rows[0]["y"] == 1
    assert rows[0]["label_source"] == "trade_outcome"
    assert len(rows[0]["x"]) == len(FEATURE_NAMES)
    assert rows[0]["features"]["rsi"] == pytest.approx(72.0)


def test_trade_outcome_loss_label():
    rows, _ = attach_features_from_trade_outcomes(
        [_rich_outcome(label=0, pnl_usd=-3.0, exit_reason="STOP_LOSS")]
    )
    assert len(rows) == 1
    assert rows[0]["y"] == 0
    assert rows[0]["exit_reason"] == "STOP_LOSS"


def test_drop_without_alert_for_ml():
    rows, suppress = attach_features_from_trade_outcomes(
        [_rich_outcome(telegram_message_id=None)]
    )
    assert rows == []
    assert suppress == set()


def test_drop_degraded_default_features():
    rows, suppress = attach_features_from_trade_outcomes(
        [
            _rich_outcome(
                context_json={},  # empty → default features
                entry_price=0.07,
            )
        ]
    )
    assert rows == []
    assert suppress == {101}


def test_exit_reason_not_used_as_y():
    # Odd but possible: TP exit with negative pnl → still follow label/pnl, not reason.
    rows, _ = attach_features_from_trade_outcomes(
        [_rich_outcome(label=0, pnl_usd=-1.0, exit_reason="TAKE_PROFIT")]
    )
    assert rows[0]["y"] == 0
    assert rows[0]["exit_reason"] == "TAKE_PROFIT"


def test_hybrid_prefers_trade_label():
    alert_rows = [
        {
            "id": 101,
            "symbol": "DOGE_USD",
            "side": "SELL",
            "y": 0,
            "x": [0.0] * len(FEATURE_NAMES),
            "label_source": "alert",
            "features": {},
        }
    ]
    trade_rows, suppress = attach_features_from_trade_outcomes(
        [_rich_outcome(telegram_message_id=101, label=1, pnl_usd=9.0)]
    )
    merged = merge_alert_and_trade_datasets(
        alert_rows, trade_rows, suppress_alert_ids=suppress
    )
    assert len(merged) == 1
    assert merged[0]["y"] == 1
    assert merged[0]["label_source"] == "trade_outcome"


def test_hybrid_suppresses_alert_when_fill_degraded():
    alert_rows = [
        {
            "id": 101,
            "symbol": "DOGE_USD",
            "side": "SELL",
            "y": 1,
            "x": [0.0] * len(FEATURE_NAMES),
            "label_source": "alert",
            "features": {},
        }
    ]
    trade_rows, suppress = attach_features_from_trade_outcomes(
        [_rich_outcome(telegram_message_id=101, context_json={}, entry_price=0.07)]
    )
    assert trade_rows == []
    assert 101 in suppress
    merged = merge_alert_and_trade_datasets(
        alert_rows, trade_rows, suppress_alert_ids=suppress
    )
    assert merged == []


def test_hybrid_keeps_multiple_fills_per_alert():
    alert_rows = [
        {
            "id": 101,
            "symbol": "DOGE_USD",
            "side": "SELL",
            "y": 0,
            "x": [0.0] * len(FEATURE_NAMES),
            "label_source": "alert",
            "features": {},
        }
    ]
    trade_rows, suppress = attach_features_from_trade_outcomes(
        [
            _rich_outcome(
                telegram_message_id=101,
                entry_exchange_order_id="entry-a",
                label=1,
                pnl_usd=2.0,
            ),
            _rich_outcome(
                telegram_message_id=101,
                entry_exchange_order_id="entry-b",
                label=0,
                pnl_usd=-1.0,
            ),
        ]
    )
    assert len(trade_rows) == 2
    merged = merge_alert_and_trade_datasets(
        alert_rows, trade_rows, suppress_alert_ids=suppress
    )
    assert len(merged) == 2
    assert {r["entry_exchange_order_id"] for r in merged} == {"entry-a", "entry-b"}
    assert all(r["label_source"] == "trade_outcome" for r in merged)


def test_label_source_meta_trade_outcomes(tmp_path, monkeypatch):
    from build_auto_ml_dataset import main as build_main

    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Missing DB URL for trade_outcomes → exit 2
    rc = build_main(
        [
            "--label-source",
            "trade_outcomes",
            "--out",
            str(tmp_path / "ds.json"),
        ]
    )
    assert rc == 2
    assert "pnl_usd" in TRADE_OUTCOME_LABEL_DEF


def test_demo_meta_still_alert_phase(tmp_path):
    from build_auto_ml_dataset import main as build_main

    ds = tmp_path / "demo.json"
    assert build_main(["--demo", "--out", str(ds)]) == 0
    meta = json.loads(ds.read_text())["meta"]
    assert meta["label_source"] == "alert"
    assert meta["phase"] == "ml-a-offline"
    assert all(r.get("label_source") == "alert" for r in json.loads(ds.read_text())["rows"])
