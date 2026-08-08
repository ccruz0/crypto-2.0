"""Sales report must not double-count one economic FILLED SELL under two IDs."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.daily_summary import DailySummaryService


def _sell(
    *,
    exchange_order_id: str,
    symbol: str = "BTC_USD",
    quantity: float = 1.89286,
    avg_price: float = 64860.47,
    order_role: str = "TAKE_PROFIT",
    exchange_update_time: datetime | None = None,
):
    return SimpleNamespace(
        exchange_order_id=exchange_order_id,
        symbol=symbol,
        quantity=quantity,
        avg_price=avg_price,
        price=avg_price,
        order_role=order_role,
        exchange_update_time=exchange_update_time
        or datetime(2026, 8, 6, 8, 30, 39, tzinfo=timezone.utc),
    )


def test_dedupe_collapses_btc_tp_dual_ids_within_window():
    """Reproduce 2026-08-06 sales report: same BTC TP under two exchange IDs."""
    t0 = datetime(2026, 8, 6, 8, 30, 39, tzinfo=timezone.utc)
    rows = [
        _sell(exchange_order_id="5755600492693736659", exchange_update_time=t0 + timedelta(seconds=3)),
        _sell(exchange_order_id="73817490102060313", exchange_update_time=t0),
        _sell(
            exchange_order_id="5755600492713365754",
            symbol="ALGO_USD",
            quantity=111.0,
            avg_price=0.0894,
            order_role="SELL",
            exchange_update_time=t0 + timedelta(hours=8),
        ),
    ]

    kept = DailySummaryService._dedupe_filled_sells_for_report(rows)
    ids = [o.exchange_order_id for o in kept]

    assert "73817490102060313" in ids
    assert "5755600492693736659" not in ids
    assert "5755600492713365754" in ids
    assert len(kept) == 2
    # Newest first (report display order)
    assert ids[0] == "5755600492713365754"


def test_dedupe_collapses_aug7_dual_ids_at_6_and_10_seconds():
    """Reproduce 2026-08-07 Bali report: DOT (6s) + BTC (10s) dual-ID lag beat 5s window."""
    rows = [
        _sell(
            exchange_order_id="5755600492745492191",
            symbol="DOT_USD",
            quantity=12.14,
            avg_price=0.8205,
            exchange_update_time=datetime(2026, 8, 7, 12, 30, 12, tzinfo=timezone.utc),
        ),
        _sell(
            exchange_order_id="73817490102063063",
            symbol="DOT_USD",
            quantity=12.14,
            avg_price=0.8205,
            exchange_update_time=datetime(2026, 8, 7, 12, 30, 6, tzinfo=timezone.utc),
        ),
        _sell(
            exchange_order_id="5755600492740665914",
            symbol="BTC_USD",
            quantity=0.00015,
            avg_price=64878.07,
            exchange_update_time=datetime(2026, 8, 7, 9, 32, 43, tzinfo=timezone.utc),
        ),
        _sell(
            exchange_order_id="73817490102062566",
            symbol="BTC_USD",
            quantity=0.00015,
            avg_price=64878.07,
            exchange_update_time=datetime(2026, 8, 7, 9, 32, 33, tzinfo=timezone.utc),
        ),
        _sell(
            exchange_order_id="5755600492748034340",
            symbol="DOGE_USD",
            quantity=1428.0,
            avg_price=0.0699,
            order_role="SELL",
            exchange_update_time=datetime(2026, 8, 7, 13, 30, 18, tzinfo=timezone.utc),
        ),
    ]

    kept = DailySummaryService._dedupe_filled_sells_for_report(rows)
    ids = {o.exchange_order_id for o in kept}

    assert ids == {
        "73817490102063063",
        "73817490102062566",
        "5755600492748034340",
    }
    assert len(kept) == 3


def test_dedupe_keeps_distinct_fills_same_symbol():
    t0 = datetime(2026, 8, 6, 8, 0, 0, tzinfo=timezone.utc)
    rows = [
        _sell(
            exchange_order_id="tp-a",
            quantity=1.0,
            avg_price=100.0,
            exchange_update_time=t0,
        ),
        _sell(
            exchange_order_id="tp-b",
            quantity=2.0,
            avg_price=100.0,
            exchange_update_time=t0 + timedelta(seconds=1),
        ),
    ]
    kept = DailySummaryService._dedupe_filled_sells_for_report(rows)
    assert {o.exchange_order_id for o in kept} == {"tp-a", "tp-b"}


def test_dedupe_keeps_same_economics_outside_window():
    t0 = datetime(2026, 8, 6, 8, 0, 0, tzinfo=timezone.utc)
    rows = [
        _sell(exchange_order_id="first", exchange_update_time=t0),
        _sell(exchange_order_id="second", exchange_update_time=t0 + timedelta(seconds=90)),
    ]
    kept = DailySummaryService._dedupe_filled_sells_for_report(rows)
    assert len(kept) == 2


def test_prior_5s_window_misses_10s_lag():
    """Guard: the 2026-08-07 regression is exactly why default moved past 5s."""
    t0 = datetime(2026, 8, 7, 9, 32, 33, tzinfo=timezone.utc)
    rows = [
        _sell(
            exchange_order_id="5755600492740665914",
            quantity=0.00015,
            avg_price=64878.07,
            exchange_update_time=t0 + timedelta(seconds=10),
        ),
        _sell(
            exchange_order_id="73817490102062566",
            quantity=0.00015,
            avg_price=64878.07,
            exchange_update_time=t0,
        ),
    ]
    kept_tight = DailySummaryService._dedupe_filled_sells_for_report(rows, window_seconds=5)
    assert len(kept_tight) == 2
    kept_default = DailySummaryService._dedupe_filled_sells_for_report(rows)
    assert len(kept_default) == 1
