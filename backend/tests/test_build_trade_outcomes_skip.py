"""Tests for build_trade_outcomes --skip-if-fresh-hours (ops hybrid retrain)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_trade_outcomes import (  # noqa: E402
    main as build_main,
    trade_outcomes_max_updated_age_hours,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'test.db'}"


def _bootstrap_trade_outcomes(db_url: str, *, updated_at: datetime) -> None:
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE trade_outcomes (
                  id INTEGER PRIMARY KEY,
                  entry_exchange_order_id TEXT NOT NULL,
                  symbol TEXT NOT NULL,
                  side TEXT NOT NULL,
                  join_status TEXT NOT NULL,
                  source TEXT NOT NULL,
                  updated_at TIMESTAMP NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO trade_outcomes (
                  entry_exchange_order_id, symbol, side, join_status, source, updated_at
                ) VALUES ('e1', 'BTC_USD', 'BUY', 'COMPLETE', 'test', :ts)
                """
            ),
            {"ts": updated_at},
        )


def test_trade_outcomes_max_updated_age_hours_fresh(tmp_path):
    now = datetime.now(timezone.utc)
    db_url = _sqlite_url(tmp_path)
    _bootstrap_trade_outcomes(db_url, updated_at=now - timedelta(hours=1))
    age = trade_outcomes_max_updated_age_hours(db_url)
    assert age < 2.0


def test_trade_outcomes_max_updated_age_hours_empty_table(tmp_path):
    db_url = _sqlite_url(tmp_path)
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE trade_outcomes (
                  id INTEGER PRIMARY KEY,
                  updated_at TIMESTAMP
                )
                """
            )
        )
    assert trade_outcomes_max_updated_age_hours(db_url) == pytest.approx(99999.0)


def test_skip_if_fresh_hours_skips_rebuild(tmp_path, capsys):
    now = datetime.now(timezone.utc)
    db_url = _sqlite_url(tmp_path)
    _bootstrap_trade_outcomes(db_url, updated_at=now - timedelta(hours=2))
    out = tmp_path / "coverage.json"
    rc = build_main(
        [
            "--database-url",
            db_url,
            "--days",
            "30",
            "--out",
            str(out),
            "--skip-if-fresh-hours",
            "26",
        ]
    )
    assert rc == 0
    assert not out.exists()
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert payload["skipped"] is True
    assert payload["reason"] == "trade_outcomes_fresh"


def test_build_auto_ml_dataset_demo_emits_heartbeats(tmp_path, capsys):
    from build_auto_ml_dataset import main as build_main

    ds = tmp_path / "demo.json"
    rc = build_main(["--demo", "--out", str(ds)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "AUTO_ML_DATASET_HEARTBEAT" in err
    assert "done" in err
