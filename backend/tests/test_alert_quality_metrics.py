"""Unit tests for scripts/alert_quality_metrics.py (pure helpers only)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from alert_quality_metrics import (  # noqa: E402
    Candle,
    composite_score,
    compute_sl_tp,
    direction_accuracy,
    expectancy_proxy,
    label_alert,
    mfe_mae,
    parse_price_from_message,
    parse_side_from_message,
    resolve_entry_price,
    rollup_segment,
    tp_before_sl,
    trend_hit,
)


def test_parse_side_and_price():
    buy = "🟢 BUY SIGNAL DETECTED\n💵 Price: $1,234.5000"
    sell = "🔴 SELL SIGNAL: ETH_USDT @ $3200.0000"
    assert parse_side_from_message(buy) == "BUY"
    assert parse_side_from_message(sell) == "SELL"
    assert parse_price_from_message(buy) == pytest.approx(1234.5)
    assert parse_price_from_message(sell) == pytest.approx(3200.0)


def test_resolve_entry_prefers_context():
    price = resolve_entry_price(
        message="💵 Price: $100.0000",
        context={"entry_price": 99.5},
        trade_entry=98.0,
    )
    assert price == pytest.approx(99.5)


def test_trend_hit_and_direction():
    assert trend_hit(100.0, 100.6, "BUY", delta=0.005) is True
    assert trend_hit(100.0, 100.4, "BUY", delta=0.005) is False
    assert trend_hit(100.0, 99.4, "SELL", delta=0.005) is True
    assert direction_accuracy(100.0, 101.0, "BUY") is True
    assert direction_accuracy(100.0, 99.0, "BUY") is False
    assert direction_accuracy(100.0, 99.0, "SELL") is True


def test_mfe_mae_buy():
    candles = [
        Candle(t=0, o=100, h=102, l=99, c=101),
        Candle(t=1, o=101, h=103, l=98, c=100),
    ]
    mfe, mae = mfe_mae(100.0, "BUY", candles)
    assert mfe == pytest.approx(0.03)
    assert mae == pytest.approx(0.02)


def test_sl_tp_and_tp_before_sl():
    sl, tp = compute_sl_tp(100.0, "BUY", atr=2.0, atr_mult=1.5, rr=1.5)
    assert sl == pytest.approx(97.0)
    assert tp == pytest.approx(104.5)
    # Hit TP first
    win = [
        Candle(t=0, o=100, h=105, l=99.5, c=104),
        Candle(t=1, o=104, h=104, l=90, c=91),
    ]
    assert tp_before_sl(100.0, "BUY", win, sl, tp) is True
    # Hit SL first
    lose = [Candle(t=0, o=100, h=100.5, l=96, c=97)]
    assert tp_before_sl(100.0, "BUY", lose, sl, tp) is False
    # Neither
    flat = [Candle(t=0, o=100, h=101, l=99, c=100.5)]
    assert tp_before_sl(100.0, "BUY", flat, sl, tp) is None


def test_expectancy_and_composite():
    assert expectancy_proxy(0.6, 0.02, 0.4, 0.01) == pytest.approx(0.008)
    score = composite_score(
        dir_1h=True,
        trend_4h=True,
        tp_sl=False,
        mfe=0.03,
        mae=0.01,
    )
    # 0.35*1 + 0.25*1 + 0.25*0 + 0.15*clip(0.02) = 0.35+0.25+0+0.003 = 0.603
    assert score == pytest.approx(0.603)


def test_label_alert_buy_uptrend():
    entry = 100.0
    t0 = 1_700_000_000_000
    candles = []
    price = entry
    for i in range(20):
        o = price
        c = price * 1.004
        candles.append(
            Candle(
                t=t0 + i * 15 * 60_000,
                o=o,
                h=max(o, c) * 1.001,
                l=min(o, c) * 0.999,
                c=c,
            )
        )
        price = c
    out = label_alert(
        side="BUY",
        entry=entry,
        entry_ts_ms=t0,
        candles=candles,
        atr=1.0,
        atr_mult=1.5,
        rr=1.5,
        delta=0.005,
        mfe_horizon_min=240,
    )
    assert out["dir_acc_1h"] is True
    assert out["trend_hit_1h"] is True
    assert out["mfe_pct"] is not None and out["mfe_pct"] > 0
    assert out["composite_score"] is not None
    assert 0.0 <= out["composite_score"] <= 1.0


def test_rollup_segment_rankable_flag():
    rows = [
        {
            "dir_acc_1h": True,
            "trend_hit_4h": True,
            "trend_hit_1h": True,
            "tp_before_sl": True,
            "mfe_pct": 0.02,
            "mae_pct": 0.01,
            "composite_score": 0.7,
        }
        for _ in range(5)
    ]
    small = rollup_segment(rows, min_n=20)
    assert small["n"] == 5
    assert small["rankable"] is False
    big = rollup_segment(rows * 4, min_n=20)
    assert big["n"] == 20
    assert big["rankable"] is True
    assert big["dir_acc_1h"] == pytest.approx(1.0)
