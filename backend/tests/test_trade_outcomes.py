"""Phase 1a: trade_outcomes join/label builder tests (fixtures only, no live DB)."""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services.trade_outcome_builder import (
    build_outcome_for_intent,
    build_outcomes_from_fixtures,
    classify_missing_exit_fill,
    compute_pnl,
    coverage_report_dict,
    has_active_protection_children,
    infer_exit_role,
    load_rows_from_db,
    select_exit_child,
    select_orphan_exit,
)
from app.utils.dry_run_orders import is_dry_run_order_id


BASE = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def test_infer_exit_role_from_type_and_role():
    assert infer_exit_role(order_role="TAKE_PROFIT") == "TAKE_PROFIT"
    assert infer_exit_role(order_role="STOP_LOSS") == "STOP_LOSS"
    assert infer_exit_role(order_type="TAKE_PROFIT_LIMIT") == "TAKE_PROFIT"
    assert infer_exit_role(order_type="STOP_LIMIT") == "STOP_LOSS"
    assert infer_exit_role(order_type="LIMIT") is None


def test_is_dry_run_order_id():
    assert is_dry_run_order_id("dry_market_1782920132")
    assert is_dry_run_order_id("dry_client_market_1")
    assert is_dry_run_order_id("dry_abc")
    assert not is_dry_run_order_id("5755600492596115675")
    assert not is_dry_run_order_id(None)
    assert not is_dry_run_order_id("")


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


def test_select_exit_child_skips_stub_closed():
    children = [
        {
            "exchange_order_id": "STUB-CLOSED-STOP_LOSS-5755600492155811564",
            "order_role": "STOP_LOSS",
            "status": "FILLED",
            "avg_price": 90.0,
            "quantity": 1.0,
            "exchange_update_time": BASE + timedelta(hours=1),
        },
        {
            "exchange_order_id": "tp-real",
            "order_role": "TAKE_PROFIT",
            "status": "FILLED",
            "avg_price": 110.0,
            "quantity": 1.0,
            "exchange_update_time": BASE + timedelta(hours=2),
        },
    ]
    chosen = select_exit_child(children)
    assert chosen is not None
    assert chosen["exchange_order_id"] == "tp-real"


def test_stub_only_exit_not_complete_train_row():
    """STUB-CLOSED-* fills must not become COMPLETE train labels."""
    intent = {
        "id": 9,
        "signal_id": 19,
        "symbol": "BTC_USD",
        "side": "BUY",
        "status": "ORDER_PLACED",
        "order_id": "e-stub",
    }
    entry = {
        "exchange_order_id": "e-stub",
        "symbol": "BTC_USD",
        "side": "BUY",
        "status": "FILLED",
        "avg_price": 100.0,
        "quantity": 1.0,
        "exchange_create_time": BASE,
    }
    children = [
        {
            "exchange_order_id": "STUB-CLOSED-STOP_LOSS-5755600492155811564",
            "parent_order_id": "e-stub",
            "order_role": "STOP_LOSS",
            "status": "FILLED",
            "avg_price": 100.0,
            "quantity": 1.0,
            "exchange_update_time": BASE + timedelta(hours=1),
        }
    ]
    from app.services.trade_outcome_builder import CoverageStats

    stats = CoverageStats()
    row = build_outcome_for_intent(intent, entry=entry, children=children, stats=stats)
    assert row is None
    assert stats.dropped["protection_cancelled_no_exit"] == 1
    assert stats.dropped.get("missing_exit_fill", 0) == 0


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
    # Even with a tempting opposite MARKET, active protection blocks orphan attribution.
    orphans = [
        {
            "exchange_order_id": "fake-flatten",
            "symbol": "ETH_USD",
            "side": "SELL",
            "order_type": "MARKET",
            "status": "FILLED",
            "avg_price": 55.0,
            "quantity": 1.0,
            "parent_order_id": None,
            "exchange_update_time": BASE + timedelta(hours=1),
        }
    ]
    entry["exchange_create_time"] = BASE
    row = build_outcome_for_intent(
        intent, entry=entry, children=children, orphan_candidates=orphans, stats=stats
    )
    assert row is None
    assert stats.dropped["still_open"] == 1
    assert stats.dropped.get("orphan_rejected_by_guards", 0) == 0
    assert stats.complete == 0
    assert has_active_protection_children(children)
    assert (
        classify_missing_exit_fill(
            entry=entry,
            entry_side="BUY",
            entry_ts=BASE,
            children=children,
            orphan_candidates=orphans,
        )
        == "still_open"
    )


def test_drop_protection_cancelled_no_exit():
    intent = {
        "id": 21,
        "signal_id": 121,
        "symbol": "DOT_USD",
        "side": "BUY",
        "status": "ORDER_PLACED",
        "order_id": "e-cancel",
    }
    entry = {
        "exchange_order_id": "e-cancel",
        "symbol": "DOT_USD",
        "side": "BUY",
        "status": "FILLED",
        "avg_price": 10.0,
        "quantity": 1.0,
        "exchange_create_time": BASE,
    }
    children = [
        {
            "exchange_order_id": "sl-cancelled",
            "parent_order_id": "e-cancel",
            "order_role": "STOP_LOSS",
            "status": "CANCELLED",
            "price": 9.0,
        },
        {
            "exchange_order_id": "tp-rejected",
            "parent_order_id": "e-cancel",
            "order_role": "TAKE_PROFIT",
            "status": "REJECTED",
            "price": 11.0,
        },
    ]
    from app.services.trade_outcome_builder import CoverageStats

    stats = CoverageStats()
    row = build_outcome_for_intent(
        intent, entry=entry, children=children, orphan_candidates=[], stats=stats
    )
    assert row is None
    assert stats.dropped["protection_cancelled_no_exit"] == 1


def test_drop_no_children():
    intent = {
        "id": 22,
        "signal_id": 122,
        "symbol": "ALGO_USD",
        "side": "BUY",
        "status": "ORDER_PLACED",
        "order_id": "e-none",
    }
    entry = {
        "exchange_order_id": "e-none",
        "symbol": "ALGO_USD",
        "side": "BUY",
        "status": "FILLED",
        "avg_price": 0.1,
        "quantity": 100.0,
        "exchange_create_time": BASE,
    }
    from app.services.trade_outcome_builder import CoverageStats

    stats = CoverageStats()
    row = build_outcome_for_intent(
        intent, entry=entry, children=[], orphan_candidates=[], stats=stats
    )
    assert row is None
    assert stats.dropped["no_children"] == 1


def test_drop_orphan_rejected_by_guards_qty():
    """Opposite MARKET exists but qty gate rejects — still dropped, not COMPLETE."""
    intent = {
        "id": 23,
        "signal_id": 123,
        "symbol": "AAVE_USD",
        "side": "BUY",
        "status": "ORDER_PLACED",
        "order_id": "e-qty",
    }
    entry = {
        "exchange_order_id": "e-qty",
        "symbol": "AAVE_USD",
        "side": "BUY",
        "status": "FILLED",
        "avg_price": 100.0,
        "quantity": 1.0,
        "exchange_create_time": BASE,
    }
    orphans = [
        {
            "exchange_order_id": "wrong-qty-exit",
            "symbol": "AAVE_USD",
            "side": "SELL",
            "order_type": "MARKET",
            "status": "FILLED",
            "avg_price": 99.0,
            "quantity": 10.0,  # far outside DEFAULT_ORPHAN_QTY_TOLERANCE
            "parent_order_id": None,
            "exchange_update_time": BASE + timedelta(hours=1),
        }
    ]
    from app.services.trade_outcome_builder import CoverageStats

    stats = CoverageStats()
    row = build_outcome_for_intent(
        intent, entry=entry, children=[], orphan_candidates=orphans, stats=stats
    )
    assert row is None
    assert stats.dropped["orphan_rejected_by_guards"] == 1
    # Guarantees attribution still rejects — not a COMPLETE.
    assert select_orphan_exit(
        entry=entry,
        entry_side="BUY",
        entry_qty=1.0,
        entry_ts=BASE,
        candidates=orphans,
    ) is None


def test_batch_excludes_dry_run_from_eligible_denom():
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
            "id": 99,
            "symbol": "ETH_USDT",
            "side": "SELL",
            "status": "ORDER_PLACED",
            "order_id": "dry_market_1782920132",
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
    }
    rows, stats = build_outcomes_from_fixtures(
        intents=intents,
        entries_by_id=entries,
        children_by_parent=children,
    )
    assert len(rows) == 1
    assert stats.intents_considered == 1  # dry-run excluded from denom
    assert stats.dropped.get("missing_entry_order", 0) == 0
    assert stats.dropped.get("dry_run_order_id", 0) == 0


def test_orphan_market_flatten_manual_or_flatten():
    """Investigation sample shape: cancelled SL/TP + opposite FILLED MARKET."""
    intent = {
        "id": 5616,
        "signal_id": 5016,
        "symbol": "AAVE_USD",
        "side": "SELL",
        "status": "ORDER_PLACED",
        "order_id": "entry-aave-5616",
    }
    entry = {
        "exchange_order_id": "entry-aave-5616",
        "symbol": "AAVE_USD",
        "side": "SELL",
        "order_type": "LIMIT",
        "status": "FILLED",
        "avg_price": 200.0,
        "quantity": 1.5,
        "exchange_create_time": BASE,
    }
    children = [
        {
            "exchange_order_id": "sl-cancelled",
            "parent_order_id": "entry-aave-5616",
            "order_role": "STOP_LOSS",
            "order_type": "STOP_LIMIT",
            "status": "CANCELLED",
            "price": 220.0,
            "quantity": 1.5,
        },
        {
            "exchange_order_id": "tp-cancelled",
            "parent_order_id": "entry-aave-5616",
            "order_role": "TAKE_PROFIT",
            "order_type": "TAKE_PROFIT_LIMIT",
            "status": "CANCELLED",
            "price": 180.0,
            "quantity": 1.5,
        },
    ]
    orphans = [
        {
            "exchange_order_id": "exit-aave-913919",
            "symbol": "AAVE_USD",
            "side": "BUY",
            "order_type": "MARKET",
            "status": "FILLED",
            "avg_price": 195.0,
            "quantity": 1.5,
            "parent_order_id": None,
            "exchange_update_time": BASE + timedelta(hours=5),
        }
    ]
    row = build_outcome_for_intent(
        intent, entry=entry, children=children, orphan_candidates=orphans
    )
    assert row is not None
    assert row["exit_reason"] == "MANUAL_OR_FLATTEN"
    assert row["exit_exchange_order_id"] == "exit-aave-913919"
    assert row["label"] == 1  # short entry 200 → exit 195
    assert row["pnl_usd"] == pytest.approx(7.5)
    meta = json.loads(row["meta_json"])
    assert meta["exit_via_orphan"] is True


def test_orphan_rejects_qty_mismatch_and_out_of_window():
    entry = {
        "exchange_order_id": "entry-buy",
        "symbol": "BTC_USD",
        "side": "BUY",
        "status": "FILLED",
        "avg_price": 100.0,
        "quantity": 2.0,
        "exchange_create_time": BASE,
    }
    # Wrong qty (would be naive first-opposite trap)
    wrong_qty = {
        "exchange_order_id": "opp-wrong-qty",
        "symbol": "BTC_USD",
        "side": "SELL",
        "order_type": "MARKET",
        "status": "FILLED",
        "avg_price": 101.0,
        "quantity": 10.0,
        "parent_order_id": None,
        "exchange_update_time": BASE + timedelta(hours=1),
    }
    # Out of 14d window
    too_late = {
        "exchange_order_id": "opp-too-late",
        "symbol": "BTC_USD",
        "side": "SELL",
        "order_type": "MARKET",
        "status": "FILLED",
        "avg_price": 101.0,
        "quantity": 2.0,
        "parent_order_id": None,
        "exchange_update_time": BASE + timedelta(days=20),
    }
    assert (
        select_orphan_exit(
            entry=entry,
            entry_side="BUY",
            entry_qty=2.0,
            entry_ts=BASE,
            candidates=[wrong_qty, too_late],
        )
        is None
    )


def test_orphan_rejects_parented_and_same_side_false_pair():
    """Guard against naive first-opposite / later same-side short entry."""
    entry = {
        "exchange_order_id": "entry-5592",
        "symbol": "ETH_USD",
        "side": "BUY",
        "status": "FILLED",
        "avg_price": 50.0,
        "quantity": 1.0,
        "exchange_create_time": BASE,
    }
    later_short_entry = {
        # Same-side FILLED MARKET after entry — not an exit for the long.
        "exchange_order_id": "later-short-entry",
        "symbol": "ETH_USD",
        "side": "BUY",
        "order_type": "MARKET",
        "status": "FILLED",
        "avg_price": 48.0,
        "quantity": 1.0,
        "parent_order_id": None,
        "exchange_update_time": BASE + timedelta(hours=2),
    }
    parented_childish = {
        "exchange_order_id": "has-parent",
        "symbol": "ETH_USD",
        "side": "SELL",
        "order_type": "MARKET",
        "status": "FILLED",
        "avg_price": 51.0,
        "quantity": 1.0,
        "parent_order_id": "someone-else",
        "exchange_update_time": BASE + timedelta(hours=1),
    }
    assert (
        select_orphan_exit(
            entry=entry,
            entry_side="BUY",
            entry_qty=1.0,
            entry_ts=BASE,
            candidates=[later_short_entry, parented_childish],
        )
        is None
    )


def test_orphan_exit_claimed_once_across_batch():
    intents = [
        {
            "id": 1,
            "symbol": "AAVE_USD",
            "side": "SELL",
            "status": "ORDER_PLACED",
            "order_id": "e1",
        },
        {
            "id": 2,
            "symbol": "AAVE_USD",
            "side": "SELL",
            "status": "ORDER_PLACED",
            "order_id": "e2",
        },
    ]
    entries = {
        "e1": {
            "exchange_order_id": "e1",
            "symbol": "AAVE_USD",
            "side": "SELL",
            "status": "FILLED",
            "avg_price": 200.0,
            "quantity": 1.0,
            "exchange_create_time": BASE,
        },
        "e2": {
            "exchange_order_id": "e2",
            "symbol": "AAVE_USD",
            "side": "SELL",
            "status": "FILLED",
            "avg_price": 201.0,
            "quantity": 1.0,
            "exchange_create_time": BASE + timedelta(minutes=10),
        },
    }
    children = {"e1": [], "e2": []}
    orphans = [
        {
            "exchange_order_id": "shared-exit",
            "symbol": "AAVE_USD",
            "side": "BUY",
            "order_type": "MARKET",
            "status": "FILLED",
            "avg_price": 195.0,
            "quantity": 1.0,
            "parent_order_id": None,
            "exchange_update_time": BASE + timedelta(hours=1),
        }
    ]
    rows, stats = build_outcomes_from_fixtures(
        intents=intents,
        entries_by_id=entries,
        children_by_parent=children,
        orphan_candidates=orphans,
    )
    assert len(rows) == 1
    assert rows[0]["exit_exchange_order_id"] == "shared-exit"
    assert stats.dropped["orphan_rejected_by_guards"] == 1


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
    assert stats.dropped["still_open"] == 1
    assert stats.dropped.get("missing_exit_fill", 0) == 0
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


def test_orphan_sql_casts_enum_columns_to_text():
    """Prod Postgres uses enums; UPPER(enum) fails — cast ::text before UPPER."""
    src = inspect.getsource(load_rows_from_db)
    assert "UPPER(status::text)" in src
    assert "UPPER(order_type::text)" in src
    assert "UPPER(order_role::text)" in src
    assert "UPPER(status)" not in src.replace("UPPER(status::text)", "")
    assert "UPPER(order_type)" not in src.replace("UPPER(order_type::text)", "")
    assert "UPPER(order_role)" not in src.replace("UPPER(order_role::text)", "")
