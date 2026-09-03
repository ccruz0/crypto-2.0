"""Alert labeling progress heartbeats (SSM visibility for hybrid retrain)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_auto_ml_dataset import build_rich_demo_alerts, main as build_main  # noqa: E402
from eval_alert_quality import evaluate_alerts, normalize_alert, synthetic_candles  # noqa: E402


def _make_fixture_alerts(n: int) -> list[dict]:
    base = build_rich_demo_alerts()[0]
    rows = []
    for i in range(n):
        row = dict(base)
        row["id"] = 10_000 + i
        ctx = dict(row.get("context_json") or {})
        ctx["fixture_adverse"] = i % 2 == 1
        row["context_json"] = ctx
        rows.append(row)
    return rows


def test_evaluate_alerts_emits_progress_every_n():
    alerts = _make_fixture_alerts(60)
    seen: list[dict] = []

    labeled, summary = evaluate_alerts(
        alerts,
        fixture_candles=True,
        on_progress=seen.append,
        heartbeat_every_n=10,
        heartbeat_every_s=9999.0,
    )

    assert summary["n_labeled"] >= 1
    assert len(labeled) >= 1
    assert len(seen) >= 5
    assert seen[0]["processed"] == 10
    assert seen[-1]["processed"] == len(alerts)
    assert seen[-1]["n_total"] == len(alerts)


def test_build_dataset_demo_emits_labeling_progress(tmp_path, capsys):
    ds = tmp_path / "demo.json"
    rc = build_main(["--demo", "--out", str(ds)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "alert_labeling_start" in err
    assert "alert_labeling_progress" in err
    assert "alert_labeling_done" in err


def test_alert_limit_env_default_applied(monkeypatch):
    monkeypatch.setenv("AUTO_ML_ALERT_LABEL_LIMIT", "777")
    from build_auto_ml_dataset import parse_args

    args = parse_args(["--database-url", "postgresql://x/y", "--out", "/tmp/x.json"])
    assert args.alert_limit == 777


def test_normalize_and_fixture_label_single_alert():
    raw = build_rich_demo_alerts()[0]
    norm = normalize_alert(raw)
    assert norm is not None
    candles = synthetic_candles(norm["entry_price"], norm["entry_ts_ms"], norm["side"])
    assert len(candles) >= 10
