"""Tests for dashboard position-count / ghost-protection helpers."""

from types import SimpleNamespace

from app.services.dashboard_position_counts import (
    collect_bases_for_position_counts,
    compute_protection_leg_stats,
    wallet_balances_by_base,
)


def test_wallet_balances_by_base():
    wallets = wallet_balances_by_base(
        [
            {"currency": "BTC", "balance": 0.00015},
            {"currency": "DOGE", "balance": -847.87},
            {"currency": "USD", "balance": 100},
        ]
    )
    assert wallets["BTC"] == 0.00015
    assert wallets["DOGE"] == -847.87
    assert wallets["USD"] == 100


def test_collect_bases_skips_fiat():
    bases = collect_bases_for_position_counts(
        [{"currency": "BTC", "balance": 1}, {"currency": "USD", "balance": 10}],
        [SimpleNamespace(base_symbol="ETH", symbol="ETH_USD")],
    )
    assert bases == ["BTC", "ETH"]


def test_ghost_tp_when_qty_exceeds_wallet():
    orders = [
        SimpleNamespace(
            order_type="TAKE_PROFIT_LIMIT",
            status="PENDING",
            base_symbol="BTC",
            symbol="BTC_USD",
            quantity=0.3,
            order_id="tp-big",
            order_role="TAKE_PROFIT",
            side="SELL",
        ),
        SimpleNamespace(
            order_type="TAKE_PROFIT_LIMIT",
            status="PENDING",
            base_symbol="BTC",
            symbol="BTC_USD",
            quantity=0.00015,
            order_id="tp-ok",
            order_role="TAKE_PROFIT",
            side="SELL",
        ),
    ]
    tp_counts, protective, alerts = compute_protection_leg_stats(
        orders, [{"currency": "BTC", "balance": 0.00015}]
    )
    assert tp_counts["BTC"] == 2
    assert protective["BTC"] == 2
    assert any(
        a["order_id"] == "tp-big" and a["reason"] == "qty_exceeds_wallet"
        for a in alerts
    )
    assert not any(a["order_id"] == "tp-ok" for a in alerts)


def test_ghost_wrong_side_cover_on_long():
    """BUY protection on a net-long wallet is wrong-side (ALGO cover ghost)."""
    orders = [
        SimpleNamespace(
            order_type="STOP_LIMIT",
            status="PENDING",
            base_symbol="ALGO",
            symbol="ALGO_USD",
            quantity=125.0,
            order_id="sl-buy-cover",
            order_role="STOP_LOSS",
            side="BUY",
        ),
        SimpleNamespace(
            order_type="TAKE_PROFIT_LIMIT",
            status="PENDING",
            base_symbol="ALGO",
            symbol="ALGO_USD",
            quantity=1149.0,
            order_id="tp-sell-long",
            order_role="TAKE_PROFIT",
            side="SELL",
        ),
    ]
    _tp, _prot, alerts = compute_protection_leg_stats(
        orders, [{"currency": "ALGO", "balance": 1010.0}]
    )
    assert any(
        a["order_id"] == "sl-buy-cover" and a["reason"] == "wrong_side_cover_on_long"
        for a in alerts
    )
    assert not any(a["order_id"] == "tp-sell-long" for a in alerts)


def test_ghost_when_no_wallet():
    orders = [
        SimpleNamespace(
            order_type="STOP_LIMIT",
            status="ACTIVE",
            base_symbol="XYZ",
            symbol="XYZ_USD",
            quantity=10,
            order_id="sl-1",
            order_role="STOP_LOSS",
            side="BUY",
        )
    ]
    _, _, alerts = compute_protection_leg_stats(orders, [])
    assert len(alerts) == 1
    assert alerts[0]["reason"] == "no_wallet"


def test_open_position_counts_wallet_fallback(monkeypatch):
    """Meaningful wallet short with bot FIFO count 0 → report 1 slot."""
    from app.services import dashboard_position_counts as dpc

    monkeypatch.setattr(
        "app.services.order_position_service.count_open_positions_for_symbol",
        lambda db, base: 0,
    )
    counts = dpc.compute_open_position_counts(
        db=None,
        bases=["HBAR", "BONK"],
        balances=[
            {"currency": "HBAR", "balance": -1474.0, "usd_value": -97.0},
            {"currency": "BONK", "balance": -20000.0, "usd_value": -0.05},
        ],
    )
    assert counts["HBAR"] == 1
    # Dust USD ignored
    assert counts.get("BONK", 0) == 0


def test_open_position_counts_keeps_bot_fifo(monkeypatch):
    from app.services import dashboard_position_counts as dpc

    monkeypatch.setattr(
        "app.services.order_position_service.count_open_positions_for_symbol",
        lambda db, base: 2 if base == "ALGO" else 0,
    )
    counts = dpc.compute_open_position_counts(
        db=None,
        bases=["ALGO"],
        balances=[{"currency": "ALGO", "balance": -1200.0, "usd_value": -100.0}],
    )
    assert counts["ALGO"] == 2
