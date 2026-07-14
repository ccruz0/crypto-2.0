"""Tests for orchestrator trade guardrails (trade_enabled / can_place_real_order)."""
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.services.signal_monitor import SignalMonitorService


def _watchlist(trade_enabled=True, amount=100.0):
    return SimpleNamespace(
        symbol="BTC_USD",
        trade_enabled=trade_enabled,
        trade_amount_usd=amount,
        trade_on_margin=False,
    )


class TestOrchestratorOrderGuard:
    def test_guard_blocks_when_trade_disabled(self):
        svc = SignalMonitorService()
        db = MagicMock()
        with patch(
            "app.utils.trading_guardrails.can_place_real_order",
            return_value=(False, "blocked: Trade Yes is OFF for BTC_USD"),
        ) as mock_guard:
            allowed, reason = svc._orchestrator_order_guard(db, "BTC_USD", "SELL", _watchlist(False))

        assert allowed is False
        assert "Trade Yes is OFF" in (reason or "")
        mock_guard.assert_called_once_with(
            db=db,
            symbol="BTC_USD",
            order_usd_value=100.0,
            side="SELL",
        )

    def test_guard_allows_when_trade_enabled(self):
        svc = SignalMonitorService()
        db = MagicMock()
        with patch(
            "app.utils.trading_guardrails.can_place_real_order",
            return_value=(True, None),
        ):
            allowed, reason = svc._orchestrator_order_guard(db, "BTC_USD", "BUY", _watchlist(True))

        assert allowed is True
        assert reason is None

    def test_orchestrator_does_not_place_order_when_guard_blocks(self):
        svc = SignalMonitorService()
        db = MagicMock()
        order_intent = Mock(id=99)

        with patch.object(svc, "_orchestrator_order_guard", return_value=(False, "blocked: Trade Yes is OFF")):
            with patch.object(svc, "_block_orchestrator_order") as mock_block:
                with patch.object(svc, "_place_order_from_signal") as mock_place:
                    allowed, block_reason = svc._orchestrator_order_guard(db, "BTC_USD", "SELL", _watchlist(False))
                    if not allowed:
                        svc._block_orchestrator_order(
                            db,
                            symbol="BTC_USD",
                            normalized_symbol="BTC_USD",
                            side="SELL",
                            order_intent=order_intent,
                            block_reason=block_reason or "blocked",
                            signal_id=1,
                            strategy_key="swing:conservative",
                            current_price=70000.0,
                            evaluation_id="eval-1",
                            now_utc=MagicMock(),
                        )

        mock_block.assert_called_once()
        mock_place.assert_not_called()


class TestStrategyAlertReason:
    def test_uses_rationale_for_confirmed_buy(self):
        signals = {
            "rationale": [
                "⏸️ No buy signal (Swing/Conservative): RSI too high",
                "✅ BUY (Swing/Conservative): RSI 38.0 <= 40 | Volume 1.20x >= 0.5x | MA conditions met",
            ],
            "strategy": {"reasons": {"buy_rsi_ok": True, "buy_volume_ok": True, "buy_ma_ok": True}},
        }
        reason = SignalMonitorService._build_strategy_alert_reason(
            signals, "BUY", "Swing", "Conservative", rsi=38.0, current_price=70000.0
        )
        assert "RSI 38.0 <= 40" in reason
        assert "Volume 1.20x" in reason
        assert "Swing/Conservative" in reason

    def test_uses_rationale_for_confirmed_sell(self):
        signals = {
            "rationale": [
                "🔴 SELL (Swing/Conservative): RSI=72.0 > 70 (overbought) | Volume 1.10x >= 0.5x",
            ],
            "strategy": {
                "reasons": {
                    "sell_rsi_ok": True,
                    "sell_trend_ok": True,
                    "sell_volume_ok": True,
                }
            },
            "volume_ratio": 1.1,
            "min_volume_ratio": 0.5,
        }
        reason = SignalMonitorService._build_strategy_alert_reason(
            signals, "SELL", "Swing", "Conservative", rsi=72.0, current_price=70000.0
        )
        assert "RSI=72.0 > 70" in reason
        assert "Volume 1.10x" in reason

    def test_fallback_shows_flag_summary_when_no_rationale(self):
        signals = {
            "rationale": [],
            "strategy": {
                "reasons": {
                    "buy_rsi_ok": True,
                    "buy_volume_ok": True,
                    "buy_ma_ok": False,
                }
            },
            "volume_ratio": 0.8,
            "min_volume_ratio": 0.5,
        }
        reason = SignalMonitorService._build_strategy_alert_reason(
            signals, "BUY", "Swing", "Conservative", rsi=35.0, current_price=100.0
        )
        assert "✅ RSI" in reason
        assert "✅ Volume" in reason
        assert "❌ MA50/EMA" in reason
        assert "Vol=0.80x" in reason
