"""Tests for per-coin preset resolution in resolve_strategy_profile."""

from unittest.mock import MagicMock, patch

from app.services.strategy_profiles import (
    RiskApproach,
    StrategyType,
    resolve_strategy_profile,
)


def _watchlist(sl_tp_mode: str):
    item = MagicMock()
    item.sl_tp_mode = sl_tp_mode
    return item


def test_preset_aggressive_wins_over_watchlist_conservative():
    cfg = {"coins": {"ETH_USDT": {"preset": "swing-aggressive"}}}
    with patch("app.services.strategy_profiles._load_config_cached", return_value=cfg):
        strategy, approach = resolve_strategy_profile(
            "ETH_USDT",
            watchlist_item=_watchlist("conservative"),
        )
    assert strategy == StrategyType.SWING
    assert approach == RiskApproach.AGGRESSIVE


def test_usd_preset_matches_usdt_symbol():
    cfg = {"coins": {"DOT_USD": {"preset": "scalp-aggressive"}}}
    with patch("app.services.strategy_profiles._load_config_cached", return_value=cfg):
        strategy, approach = resolve_strategy_profile("DOT_USDT")
    assert strategy == StrategyType.SCALP
    assert approach == RiskApproach.AGGRESSIVE


def test_preset_without_suffix_falls_back_to_watchlist_approach():
    cfg = {"coins": {"BTC_USDT": {"preset": "swing"}}}
    with patch("app.services.strategy_profiles._load_config_cached", return_value=cfg):
        strategy, approach = resolve_strategy_profile(
            "BTC_USDT",
            watchlist_item=_watchlist("aggressive"),
        )
    assert strategy == StrategyType.SWING
    assert approach == RiskApproach.AGGRESSIVE


def test_no_preset_defaults_to_swing_conservative():
    cfg = {"coins": {}}
    with patch("app.services.strategy_profiles._load_config_cached", return_value=cfg):
        strategy, approach = resolve_strategy_profile("ALGO_USDT")
    assert strategy == StrategyType.SWING
    assert approach == RiskApproach.CONSERVATIVE
