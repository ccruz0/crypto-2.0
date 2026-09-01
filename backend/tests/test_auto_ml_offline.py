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
    enrich_outcomes_with_nearest_signal_context,
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


def test_hybrid_fallback_uses_alert_features_for_degraded_fill():
    alert_feats = {
        "rsi": 72.0,
        "ma50_dist": 0.01,
        "ma200_dist": 0.02,
        "ema10_dist": 0.005,
        "volume_ratio": 1.2,
        "atr_pct": 0.01,
        "strategy_index": 0.7,
        "side_buy": 0.0,
        "hour_utc_norm": 0.5,
    }
    fallback = {
        101: {
            "id": 101,
            "features": alert_feats,
            "x": [alert_feats[n] for n in FEATURE_NAMES],
        }
    }
    rows, suppress = attach_features_from_trade_outcomes(
        [_rich_outcome(context_json={}, entry_price=0.07, label=1)],
        feature_fallback_by_id=fallback,
    )
    assert len(rows) == 1
    assert suppress == set()
    assert rows[0]["y"] == 1
    assert rows[0]["label_source"] == "trade_outcome"
    assert rows[0]["features"]["rsi"] == pytest.approx(72.0)


def test_hybrid_keep_degraded_emits_fill_without_fallback():
    rows, suppress = attach_features_from_trade_outcomes(
        [_rich_outcome(context_json={}, entry_price=0.07, label=0)],
        keep_degraded=True,
    )
    assert len(rows) == 1
    assert suppress == set()
    assert rows[0]["y"] == 0
    assert rows[0]["label_source"] == "trade_outcome"


def test_enrich_nearest_signal_context_within_6h():
    entry_ts = "2026-07-01T12:00:00+00:00"
    outcomes = [
        {
            "telegram_message_id": 900,
            "symbol": "DOGE_USD",
            "side": "SELL",
            "entry_price": 0.07,
            "entry_ts": entry_ts,
            "label": 1,
            "context_json": {
                "symbol": "DOGE_USD",
                "order_id": "1",
                "exchange_order_id": "1",
            },
        }
    ]
    alerts = [
        {
            "id": 101,
            "symbol": "DOGE_USDT",
            "timestamp": "2026-07-01T11:00:00+00:00",  # 1h prior
            "message": (
                "SELL SIGNAL DOGE_USDT 0.07 Auto/Conservative | "
                "RSI=72.0, Price=0.07, MA50=0.069, EMA10=0.0695, MA200=0.06"
            ),
            "context_json": {"symbol": "DOGE_USDT"},
        },
        {
            "id": 102,
            "symbol": "DOGE_USDT",
            "timestamp": "2026-07-01T04:00:00+00:00",  # 8h prior — outside 6h
            "message": "RSI=20.0, MA50=0.05, MA200=0.04, EMA10=0.05",
            "context_json": {},
        },
    ]
    enriched, stats = enrich_outcomes_with_nearest_signal_context(
        outcomes, alerts, max_skew_seconds=6 * 3600
    )
    assert stats["enriched"] == 1
    assert enriched[0]["context_json"]["rsi"] == pytest.approx(72.0)
    assert enriched[0]["signal_context_telegram_id"] == 101
    rows, _ = attach_features_from_trade_outcomes(enriched)
    assert len(rows) == 1
    assert rows[0]["features"]["rsi"] == pytest.approx(72.0)


def test_parse_indicators_spaced_ma_and_volume():
    from alert_quality_metrics import parse_indicators_from_message

    got = parse_indicators_from_message(
        "SELL SIGNAL: AAVE_USD - MA trend reversal: MA50 90.27 < EMA10 91.33 | "
        "RSI=92.1 > 70 (overbought) | Volume 2.21x >= 1.0x"
    )
    assert got["rsi"] == pytest.approx(92.1)
    assert got["ma50"] == pytest.approx(90.27)
    assert got["ema10"] == pytest.approx(91.33)
    assert got["volume_ratio"] == pytest.approx(2.21)



def test_features_from_alert_row_parses_message_when_context_empty():
    from auto_ml_features import features_from_alert_row

    feats = features_from_alert_row(
        {
            "side": "BUY",
            "entry_price": 100.0,
            "context_json": {},
            "message": "BUY SIGNAL X RSI=33.0, Price=100, MA50=98, EMA10=99, MA200=90",
        }
    )
    assert feats["rsi"] == pytest.approx(33.0)
    assert feats["ma50_dist"] == pytest.approx(0.02)



def test_enrich_nearest_signal_skips_when_outside_window():
    outcomes = [
        {
            "telegram_message_id": 901,
            "symbol": "ETH_USD",
            "entry_price": 3000.0,
            "entry_ts": "2026-07-01T12:00:00+00:00",
            "label": 0,
            "context_json": {"order_id": "x"},
        }
    ]
    alerts = [
        {
            "id": 1,
            "symbol": "ETH_USD",
            "timestamp": "2026-07-01T01:00:00+00:00",  # 11h
            "context_json": {"rsi": 40, "ma50": 2900, "ma200": 2800, "ema10": 2950, "atr": 10},
        }
    ]
    enriched, stats = enrich_outcomes_with_nearest_signal_context(
        outcomes, alerts, max_skew_seconds=6 * 3600
    )
    assert stats["no_match"] == 1
    assert "rsi" not in (enriched[0].get("context_json") or {})


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


def test_hybrid_suppresses_alert_when_complete_fill_known_but_omitted():
    """COMPLETE fill exists in DB but was not attached as a trade row → drop sim."""
    alert_rows = [
        {
            "id": 202,
            "symbol": "DOT_USD",
            "side": "BUY",
            "y": 1,
            "x": [0.0] * len(FEATURE_NAMES),
            "label_source": "alert",
            "features": {},
        },
        {
            "id": 303,
            "symbol": "ETH_USD",
            "side": "BUY",
            "y": 0,
            "x": [0.0] * len(FEATURE_NAMES),
            "label_source": "alert",
            "features": {},
        },
    ]
    # Simulate builder union: complete_ids from DB, trade_rows empty for 202.
    merged = merge_alert_and_trade_datasets(
        alert_rows, [], suppress_alert_ids={202}
    )
    assert len(merged) == 1
    assert merged[0]["id"] == 303
    assert merged[0]["label_source"] == "alert"


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


def test_short_trade_outcome_enters_ml_labels():
    """SELL-side short round-trip (BUY cover exit) must produce a training row."""
    outcome = {
        "telegram_message_id": 777,
        "symbol": "ALGO_USD",
        "side": "SELL",
        "entry_price": 100.0,
        "entry_ts": "2026-08-01T12:00:00+00:00",
        "label": 1,
        "pnl_usd": 10.0,
        "exit_reason": "TAKE_PROFIT",
        "entry_exchange_order_id": "short-entry-777",
        "context_json": {
            "rsi": 78,
            "ma50": 99.0,
            "ma200": 95.0,
            "ema10": 98.0,
            "volume_ratio": 1.1,
            "atr": 2.0,
            "strategy_index": 65,
        },
    }
    rows, suppress = attach_features_from_trade_outcomes([outcome])
    assert len(rows) == 1
    assert rows[0]["side"] == "SELL"
    assert rows[0]["y"] == 1
    assert rows[0]["label_source"] == "trade_outcome"
    assert rows[0]["features"]["side_buy"] == pytest.approx(0.0)
    assert suppress == set()
