"""Tests for the /signals endpoint's gated, fail-closed signal source.

These lock in the fix that aligns the dashboard's served `signals.buy/sell` with
the trading ENGINE's actual decision (`calculate_trading_signals`), instead of a
laxer, ungated rule (`rsi > threshold AND ma50 < ema10`) that made overbought-
but-low-volume symbols (e.g. DGB) falsely show the red SELL state on the dashboard.

`compute_engine_signals`:
- derives BUY/SELL ONLY from the engine's volume-gated decision, and
- FAILS CLOSED (returns buy=sell=False) when the decision cannot be computed.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.api.routes_signals import compute_engine_signals, period_volume_for_engine
from app.services.strategy_profiles import StrategyType, RiskApproach


def _wl_item():
    """Minimal canonical watchlist item with the attributes the helper reads."""
    return SimpleNamespace(buy_target=None, purchase_price=None, trade_amount_usd=10.0)


# DGB-like indicators: overbought RSI, EMA10 > MA50 (reversal), volume 0.27x (< 0.5x gate).
_DGB = dict(
    symbol="DGB_USD",
    current_price=0.0024990,
    rsi=69.43,
    atr=0.00005,
    ma50=0.0024186,
    ma200=0.0025084,
    ema10=0.0024656,
)


class TestComputeEngineSignalsFailClosed:
    def test_no_db_fails_closed(self):
        """No DB session -> never fall back to an ungated rule."""
        buy, sell, state = compute_engine_signals(
            db=None, current_volume=27.0, avg_volume=100.0, **_DGB
        )
        assert (buy, sell, state) == (False, False, None)

    @patch("app.api.routes_signals.DB_AVAILABLE", True)
    @patch("app.services.watchlist_selector.get_canonical_watchlist_item", return_value=None)
    def test_missing_watchlist_item_fails_closed(self, _wl):
        buy, sell, state = compute_engine_signals(
            db=MagicMock(), current_volume=27.0, avg_volume=100.0, **_DGB
        )
        assert (buy, sell, state) == (False, False, None)

    @patch("app.api.routes_signals.DB_AVAILABLE", True)
    @patch("app.services.trading_signals.calculate_trading_signals", side_effect=RuntimeError("boom"))
    @patch("app.services.strategy_profiles.resolve_strategy_profile",
           return_value=(StrategyType.SWING, RiskApproach.AGGRESSIVE))
    @patch("app.services.watchlist_selector.get_canonical_watchlist_item")
    def test_engine_exception_fails_closed(self, mock_wl, _resolve, _calc):
        mock_wl.return_value = _wl_item()
        buy, sell, state = compute_engine_signals(
            db=MagicMock(), current_volume=27.0, avg_volume=100.0, **_DGB
        )
        assert (buy, sell, state) == (False, False, None)


class TestComputeEngineSignalsPassThrough:
    @patch("app.api.routes_signals.DB_AVAILABLE", True)
    @patch("app.services.config_loader.get_strategy_rules", return_value={"rsi": {"sellAbove": 68}})
    @patch("app.services.trading_signals.calculate_trading_signals")
    @patch("app.services.strategy_profiles.resolve_strategy_profile",
           return_value=(StrategyType.SWING, RiskApproach.AGGRESSIVE))
    @patch("app.services.watchlist_selector.get_canonical_watchlist_item")
    def test_passes_through_engine_decision(self, mock_wl, _resolve, mock_calc, _rules):
        """The served decision is exactly what the engine returns (no second rule)."""
        mock_wl.return_value = _wl_item()
        mock_calc.return_value = {
            "buy_signal": False,
            "sell_signal": True,
            "strategy": {"decision": "SELL"},
        }
        buy, sell, state = compute_engine_signals(
            db=MagicMock(), current_volume=100.0, avg_volume=100.0, **_DGB
        )
        assert buy is False
        assert sell is True
        assert state == {"decision": "SELL"}


class TestDgbVolumeGateRealEngine:
    """Integration with the REAL engine (only DB helpers mocked)."""

    @patch("app.api.routes_signals.DB_AVAILABLE", True)
    @patch("app.services.strategy_profiles.resolve_strategy_profile",
           return_value=(StrategyType.SWING, RiskApproach.AGGRESSIVE))
    @patch("app.services.watchlist_selector.get_canonical_watchlist_item")
    def test_dgb_overbought_but_low_volume_does_not_sell(self, mock_wl, _resolve):
        """DGB case: RSI 69.43 + reversal but volume 0.27x < 0.5x -> NO sell -> not red."""
        mock_wl.return_value = _wl_item()
        buy, sell, _state = compute_engine_signals(
            db=MagicMock(), current_volume=27.0, avg_volume=100.0, **_DGB
        )
        assert sell is False

    @patch("app.api.routes_signals.DB_AVAILABLE", True)
    @patch("app.services.strategy_profiles.resolve_strategy_profile",
           return_value=(StrategyType.SWING, RiskApproach.AGGRESSIVE))
    @patch("app.services.watchlist_selector.get_canonical_watchlist_item")
    def test_overbought_with_sufficient_volume_sells(self, mock_wl, _resolve):
        """Same overbought + reversal, but volume 2.0x >= 0.5x and RSI well above sellAbove -> sell."""
        mock_wl.return_value = _wl_item()
        params = dict(_DGB)
        params["rsi"] = 85.0
        buy, sell, _state = compute_engine_signals(
            db=MagicMock(), current_volume=200.0, avg_volume=100.0, **params
        )
        assert sell is True


class TestPeriodVolumeForEngine:
    """Watchlist must feed the engine the same period volume Signal Monitor uses."""

    def test_prefers_period_volume_over_24h(self):
        # Live CRO_USD: period ~26.5k vs 24h ~3.48M would look like 73× if mixed.
        assert period_volume_for_engine(26510.0, 3483861.0) == 26510.0

    def test_falls_back_to_24h_divided_by_24(self):
        assert period_volume_for_engine(None, 2400.0) == 100.0
        assert period_volume_for_engine(0.0, 2400.0) == 100.0

    def test_missing_both_returns_none(self):
        assert period_volume_for_engine(None, None) is None
        assert period_volume_for_engine(0.0, 0.0) is None


# CRO_USD 2026-08-14: RSI ~77, MA50 < EMA10, Auto/Conservative volumeMinRatio 1.0.
_CRO = dict(
    symbol="CRO_USD",
    current_price=0.04832,
    rsi=77.02,
    atr=0.000247,
    ma50=0.046913,
    ma200=0.049141,
    ema10=0.047464,
)


class TestCroPeriodVolumeDoesNotInflateSell:
    """Regression: Watchlist painted red SELL while Telegram stayed silent.

    /signals used to pass volume_24h into the engine (~73× vs avg) while the
    dashboard column showed period volume_ratio 0.56× (< auto 1.0× min).
    Signal Monitor already uses period volume, so no Telegram SELL fired.
    """

    @patch("app.api.routes_signals.DB_AVAILABLE", True)
    @patch("app.services.strategy_profiles.resolve_strategy_profile",
           return_value=(StrategyType.AUTO, RiskApproach.CONSERVATIVE))
    @patch("app.services.watchlist_selector.get_canonical_watchlist_item")
    def test_period_volume_below_min_does_not_sell(self, mock_wl, _resolve):
        mock_wl.return_value = _wl_item()
        buy, sell, state = compute_engine_signals(
            db=MagicMock(),
            current_volume=26510.0,
            avg_volume=47286.59,
            **_CRO,
        )
        assert sell is False
        assert buy is False
        if state and isinstance(state, dict):
            reasons = state.get("reasons") or {}
            assert reasons.get("sell_volume_ok") is False

    @patch("app.api.routes_signals.DB_AVAILABLE", True)
    @patch("app.services.strategy_profiles.resolve_strategy_profile",
           return_value=(StrategyType.AUTO, RiskApproach.CONSERVATIVE))
    @patch("app.services.watchlist_selector.get_canonical_watchlist_item")
    def test_passing_raw_24h_volume_would_falsely_sell(self, mock_wl, _resolve):
        """Documents the old bug: feeding volume_24h as current_volume trips SELL."""
        mock_wl.return_value = _wl_item()
        _buy, sell, _state = compute_engine_signals(
            db=MagicMock(),
            current_volume=3483861.0,
            avg_volume=47286.59,
            **_CRO,
        )
        assert sell is True
