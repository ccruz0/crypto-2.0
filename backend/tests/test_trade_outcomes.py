"""Phase 1a: trade_outcomes join/label builder tests (fixtures only, no live DB)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.trade_outcome_builder import (
    build_outcome_for_intent,
    build_outcomes_from_fixtures,
    compute_pnl,
    coverage_report_dict,
    infer_exit_role,
    select_exit_child,
)


BASE = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def test_infer_exit_role_from_type_and_role():
    assert infer_exit_role(order_role="TAKE_PROFIT") == "TAKE_PROFIT"
    assert infer_exit_role(order_role="STOP_LOSS") == "STOP_LOSS"
    assert infer_exit_role(order_type="TAKE_PROFIT_LIMIT") == "TAKE_PROFIT"
    assert infer_exit_role(order_type="STOP_LIMIT") == "STOP_LOSS"
    assert infer_exit_role(order_type="LIMIT") is None


def test_compute_pnl_long_and_short():
    usd, pct = compute_pnl(side="BUY", entry_price=100.0, exit_price=110.0, quantity=2.0)
    assert usd == pytest.approx(20.0)
    assert pct == pytest.approx(10.0)
    usd_s, pct_s = compute_pnl(side="SELL", entry_price=100.0, exit_price=90.0, quantity=1.0)
    assert usd_s == pytest.approx(10.0)
    assert pct_s == pytest.approx(10.0)


def test_select_exit_child_earliest_filled():
    children = [
        {
            "exchange_order_id": "tp",
            "order_role": "TAKE_PROFIT",
            "status": "FILLED",
            "avg_price": 110,
            "exchange_update_time": BASE + timedelta(hours=3),
        },
        {
            "exchange_order_id": "sl",
            "order_role": "STOP_LOSS",
            "status": "FILLED",
            "avg_price": 90,
            "exchange_update_time": BASE + timedelta(hours=1),
        },
    ]
    chosen = select_exit_child(children)
    assert chosen is not None
    assert chosen["exchange_order_id"] == "sl"


def test_complete_round_trip_tp_win():
    intent = {
        "id": 1,
        "signal_id": 10,
        "symbol": "BTC_USD",
        "side": "BUY",
        "status": "ORDER_PLACED",
        "order_id": "e1",
    }
    entry = {
        "exchange_order_id": "e1",
        "symbol": "BTC_USD",
        "side": "BUY",
        "status": "FILLED",
        "avg_price": 100.0,
        "quantity": 1.0,
        "exchange_create_time": BASE,
    }
    children = [
        {
            "exchange_order_id": "tp1",
            "order_role": "TAKE_PROFIT",
            "order_type": "TAKE_PROFIT_LIMIT",
            "status": "FILLED",
            "avg_price": 110.0,
            "quantity": 1.0,
            "exchange_update_time": BASE + timedelta(hours=2),
        }
    ]
    row = build_outcome_for_intent(intent, entry=entry, children=children)
    assert row is not None
    assert row["label"] == 1
    assert row["exit_reason"] == "TAKE_PROFIT"
    assert row["pnl_usd"] == pytest.approx(10.0)
    assert row["hold_seconds"] == 7200
    assert row["telegram_message_id"] == 10
    assert row["join_status"] == "COMPLETE"


def test_drop_open_position_missing_exit():
    intent = {
        "id": 2,
        "signal_id": 11,
        "symbol": "ETH_USD",
        "side": "BUY",
        "status": "ORDER_PLACED",
        "order_id": "e2",
    }
    entry = {
        "exchange_order_id": "e2",
        "status": "FILLED",
        "avg_price": 50.0,
        "quantity": 1.0,
        "side": "BUY",
        "symbol": "ETH_USD",
    }
    children = [
        {
            "exchange_order_id": "tp-open",
            "order_role": "TAKE_PROFIT",
            "status": "ACTIVE",
            "price": 60.0,
        }
    ]
    from app.services.trade_outcome_builder import CoverageStats

    stats = CoverageStats()
    row = build_outcome_for_intent(intent, entry=entry, children=children, stats=stats)
    assert row is None
    assert stats.dropped["missing_exit_fill"] == 1
    assert stats.complete == 0


def test_batch_coverage_demo_shape():
    intents = [
        {
            "id": 1,
            "signal_id": 101,
            "symbol": "BTC_USD",
            "side": "BUY",
            "status": "ORDER_PLACED",
            "order_id": "entry-win",
        },
        {
            "id": 2,
            "signal_id": 102,
            "symbol": "ETH_USD",
            "side": "BUY",
            "status": "ORDER_PLACED",
            "order_id": "entry-loss",
        },
        {
            "id": 3,
            "signal_id": 103,
            "symbol": "SOL_USD",
            "side": "BUY",
            "status": "ORDER_PLACED",
            "order_id": "entry-open",
        },
    ]
    entries = {
        "entry-win": {
            "exchange_order_id": "entry-win",
            "symbol": "BTC_USD",
            "side": "BUY",
            "status": "FILLED",
            "avg_price": 100.0,
            "quantity": 1.0,
            "exchange_create_time": BASE,
        },
        "entry-loss": {
            "exchange_order_id": "entry-loss",
            "symbol": "ETH_USD",
            "side": "BUY",
            "status": "FILLED",
            "avg_price": 50.0,
            "quantity": 2.0,
            "exchange_create_time": BASE,
        },
        "entry-open": {
            "exchange_order_id": "entry-open",
            "symbol": "SOL_USD",
            "side": "BUY",
            "status": "FILLED",
            "avg_price": 10.0,
            "quantity": 5.0,
            "exchange_create_time": BASE,
        },
    }
    children = {
        "entry-win": [
            {
                "exchange_order_id": "tp-win",
                "parent_order_id": "entry-win",
                "order_role": "TAKE_PROFIT",
                "status": "FILLED",
                "avg_price": 110.0,
                "quantity": 1.0,
                "exchange_update_time": BASE + timedelta(hours=2),
            },
        ],
        "entry-loss": [
            {
                "exchange_order_id": "sl-loss",
                "parent_order_id": "entry-loss",
                "order_role": "STOP_LOSS",
                "status": "FILLED",
                "avg_price": 45.0,
                "quantity": 2.0,
                "exchange_update_time": BASE + timedelta(hours=1),
            },
        ],
        "entry-open": [
            {
                "exchange_order_id": "tp-open",
                "parent_order_id": "entry-open",
                "order_role": "TAKE_PROFIT",
                "status": "ACTIVE",
                "price": 12.0,
            },
        ],
    }
    rows, stats = build_outcomes_from_fixtures(
        intents=intents,
        entries_by_id=entries,
        children_by_parent=children,
        alerts_by_id={101: {"id": 101}, 102: {"id": 102}},
    )
    assert len(rows) == 2
    assert stats.complete == 2
    assert stats.dropped["missing_exit_fill"] == 1
    assert stats.join_coverage_pct() == pytest.approx(66.67)
    labels = sorted(r["label"] for r in rows)
    assert labels == [0, 1]
    report = coverage_report_dict(rows, stats)
    assert report["n_positive"] == 1
    assert report["n_negative"] == 1
    assert "Phase 1b" in report["note"] or "1b" in report["note"]


def test_trade_outcome_model_importable():
    from app.models.trade_outcome import TradeOutcome
    from app.models import TradeOutcome as Reexported

    assert TradeOutcome.__tablename__ == "trade_outcomes"
    assert Reexported is TradeOutcome
