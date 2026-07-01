"""Tests for ALLOW_SHORTING margin-short bypass in signal_monitor SELL path."""

import asyncio
import os
from unittest.mock import MagicMock, patch

from app.core.trading_invariants_week5 import REASON_SELL_REQUIRES_POSITION, validate_trading_decision
from app.services.risk_guard import shorting_enabled
from app.services.signal_monitor import SignalMonitorService


def _watchlist(*, trade_on_margin: bool):
    item = MagicMock()
    item.trade_amount_usd = 10.0
    item.trade_on_margin = trade_on_margin
    return item


async def _run_sell(*, trade_on_margin: bool, open_positions: int, env: dict | None = None):
    svc = SignalMonitorService()
    db = MagicMock()
    captured: dict = {}

    def _validate(**kwargs):
        captured.update(kwargs)
        return validate_trading_decision(**kwargs)

    env = env or {}
    with patch.dict(os.environ, env, clear=False):
        with patch(
            "app.services.order_position_service.count_open_positions_for_symbol",
            return_value=open_positions,
        ):
            with patch(
                "app.core.trading_invariants_week5.validate_trading_decision",
                side_effect=_validate,
            ):
                with patch("app.utils.live_trading.get_live_trading_status", return_value=False):
                    with patch(
                        "app.services.live_trading_gate.assert_exchange_mutation_allowed",
                    ):
                        with patch(
                            "app.services.signal_monitor.trade_client.place_market_order",
                            return_value={"order_id": "dry_sell_1", "status": "FILLED"},
                        ):
                            result = await svc._place_order_from_signal(
                                db,
                                "ETH_USDT",
                                "SELL",
                                _watchlist(trade_on_margin=trade_on_margin),
                                3000.0,
                            )
    return result, captured


def test_shorting_disabled_by_default():
    with patch.dict(os.environ, {}, clear=True):
        assert shorting_enabled() is False


def test_sell_margin_without_position_blocked_when_shorting_off():
    result, captured = asyncio.run(
        _run_sell(trade_on_margin=True, open_positions=0, env={})
    )
    assert captured.get("position_exists") is False
    assert result.get("error") == REASON_SELL_REQUIRES_POSITION
    assert result.get("blocked") is True


def test_sell_margin_without_position_allowed_when_shorting_on():
    result, captured = asyncio.run(
        _run_sell(
            trade_on_margin=True,
            open_positions=0,
            env={"ALLOW_SHORTING": "true"},
        )
    )
    assert captured.get("position_exists") is True
    assert result.get("error") != REASON_SELL_REQUIRES_POSITION
    assert result.get("order_id") == "dry_sell_1"


def test_sell_spot_without_position_blocked_even_when_shorting_on():
    result, captured = asyncio.run(
        _run_sell(
            trade_on_margin=False,
            open_positions=0,
            env={"ALLOW_SHORTING": "true"},
        )
    )
    assert captured.get("position_exists") is False
    assert result.get("error") == REASON_SELL_REQUIRES_POSITION
    assert result.get("blocked") is True


def test_sell_with_existing_position_allowed_without_shorting_flag():
    result, captured = asyncio.run(
        _run_sell(trade_on_margin=True, open_positions=1, env={})
    )
    assert captured.get("position_exists") is True
    assert result.get("error") != REASON_SELL_REQUIRES_POSITION
    assert result.get("order_id") == "dry_sell_1"
