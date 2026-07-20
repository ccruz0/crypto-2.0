"""Tests for system core drawdown guard and block reason classification."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.system_core_trade_guards import (
    _maybe_rebaseline_stale_peak,
    _daily_drawdown_violation,
)
from app.utils.decision_reason import ReasonCode, classify_exchange_error


def test_classify_system_core_daily_drawdown():
    msg = "system_core_daily_drawdown dd_pct=50.00 peak=188487.58 now=94234.46"
    assert classify_exchange_error(msg) == ReasonCode.SYSTEM_CORE_DAILY_DRAWDOWN.value


def test_classify_one_active_trade_per_coin_not_exchange_unknown():
    msg = "system_core_one_active_trade_per_coin"
    assert classify_exchange_error(msg) == ReasonCode.ONE_ACTIVE_TRADE_PER_COIN.value
    assert classify_exchange_error(msg) != ReasonCode.EXCHANGE_ERROR_UNKNOWN.value
    # Wrapped forms must still classify
    assert (
        classify_exchange_error(f"Blocked: {msg}")
        == ReasonCode.ONE_ACTIVE_TRADE_PER_COIN.value
    )


def test_rebaseline_stale_peak_when_peak_is_double_current():
    state = {"date": "2026-06-28", "peak_usd": 188487.58}
    updated = _maybe_rebaseline_stale_peak(state, 94234.46)
    assert updated["peak_usd"] == 94234.46


def test_daily_drawdown_not_triggered_after_rebaseline():
    db = MagicMock()
    state = {"date": "2026-06-28", "peak_usd": 188487.58}

    with patch("app.services.system_core_trade_guards._GUARDS_ON", True), patch(
        "app.services.system_core_trade_guards._MAX_DRAWDOWN_PCT", 5.0
    ), patch(
        "app.services.system_core_trade_guards._net_equity_usd", return_value=94234.46
    ), patch(
        "app.services.system_core_trade_guards._read_state", return_value=state
    ), patch(
        "app.services.system_core_trade_guards._write_state"
    ) as mock_write, patch(
        "app.services.system_core_trade_guards.datetime"
    ) as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-06-28"
        blocked, reason = _daily_drawdown_violation(db)

    assert blocked is False
    assert reason == ""
    mock_write.assert_called_once()
