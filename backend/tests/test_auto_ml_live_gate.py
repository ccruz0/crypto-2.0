"""PR-ML-B: Auto ML live score gate (default off)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.auto_entry_features import FEATURE_NAMES, FEATURE_VERSION, extract_features, feature_vector
from app.services.auto_entry_model import (
    apply_auto_ml_buy_gate,
    auto_ml_enabled,
    reset_model_cache,
    score_auto_buy_candidate,
)
from app.services.strategy_profiles import RiskApproach, StrategyType


def test_feature_vector_length_matches_names():
    feats = extract_features(
        side="BUY",
        entry_price=100.0,
        rsi=30.0,
        ma50=98.0,
        ma200=90.0,
        ema10=99.0,
        volume_ratio=1.2,
        atr=2.0,
        strategy_index=80.0,
    )
    assert len(feature_vector(feats)) == len(FEATURE_NAMES)
    assert feats["strategy_index"] == pytest.approx(0.8)
    assert FEATURE_VERSION == 1


def test_auto_ml_enabled_default_off(monkeypatch):
    monkeypatch.delenv("AUTO_ML_ENABLED", raising=False)
    assert auto_ml_enabled() is False


def test_score_fail_open_without_model(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_ML_MODEL_PATH", str(tmp_path / "missing.joblib"))
    monkeypatch.setenv("AUTO_ML_ENABLED", "true")
    monkeypatch.setenv("AUTO_ML_SHADOW_LOG", "false")
    reset_model_cache()
    result = score_auto_buy_candidate(symbol="BTC_USDT", price=65000.0, rsi=28.0)
    assert result.score is None
    assert result.passed is None
    assert result.gate_enabled is True


def test_gate_blocks_when_enabled_and_score_low(monkeypatch):
    monkeypatch.setenv("AUTO_ML_ENABLED", "true")
    monkeypatch.setenv("AUTO_ML_THRESHOLD", "0.7")
    monkeypatch.setenv("AUTO_ML_SHADOW_LOG", "false")
    reset_model_cache()

    fake = MagicMock()
    fake.classes_ = [0, 1]
    fake.predict_proba.return_value = [[0.8, 0.2]]  # P(good)=0.2 < 0.7

    import app.services.auto_entry_model as mod

    monkeypatch.setattr(mod, "_load_model", lambda force=False: fake)
    result = apply_auto_ml_buy_gate(symbol="ETH_USDT", price=3000.0, rsi=25.0)
    assert result.score == pytest.approx(0.2)
    assert result.passed is False
    assert result.gate_enabled is True


def test_gate_passes_when_score_high(monkeypatch):
    monkeypatch.setenv("AUTO_ML_ENABLED", "true")
    monkeypatch.setenv("AUTO_ML_THRESHOLD", "0.5")
    monkeypatch.setenv("AUTO_ML_SHADOW_LOG", "false")
    reset_model_cache()

    fake = MagicMock()
    fake.classes_ = [0, 1]
    fake.predict_proba.return_value = [[0.1, 0.9]]

    import app.services.auto_entry_model as mod

    monkeypatch.setattr(mod, "_load_model", lambda force=False: fake)
    result = apply_auto_ml_buy_gate(symbol="ETH_USDT", price=3000.0, rsi=25.0)
    assert result.passed is True


def test_trading_signals_auto_ml_block(monkeypatch):
    """AUTO + rules BUY candidate + low ML score → WAIT when gate on."""
    monkeypatch.setenv("AUTO_ML_ENABLED", "true")
    monkeypatch.setenv("AUTO_ML_THRESHOLD", "0.9")
    monkeypatch.setenv("AUTO_ML_SHADOW_LOG", "false")

    fake = MagicMock()
    fake.classes_ = [0, 1]
    fake.predict_proba.return_value = [[0.95, 0.05]]

    import app.services.auto_entry_model as mod

    monkeypatch.setattr(mod, "_load_model", lambda force=False: fake)

    # Stub strategy rules so BUY flags can all pass
    rules = {
        "rsi": {"buyBelow": 40, "sellAbove": 70},
        "maChecks": {"requirePriceAboveMa200": False, "requireMa50AboveMa200": False},
        "volumeMinRatio": 0.1,
        "trendFilters": {},
        "sl": {"atrMult": 1.5, "fallbackPct": 3.0},
        "tp": {"rr": 1.5},
    }
    monkeypatch.setattr(
        "app.services.trading_signals.get_strategy_rules",
        lambda *a, **k: rules,
    )
    monkeypatch.setattr(
        "app.services.trading_signals.should_trigger_buy_signal",
        lambda **kwargs: __import__("app.services.trading_signals", fromlist=["BuyDecision"]).BuyDecision(
            should_buy=True,
            reasons=["RSI ok"],
            missing_indicators=[],
            condition_flags={"rsi_ok": True, "ma_ok": True},
        ),
    )

    from app.services.trading_signals import calculate_trading_signals

    out = calculate_trading_signals(
        symbol="AAVE_USD",
        price=95.0,
        rsi=28.0,
        atr14=2.0,
        ma50=94.0,
        ma200=90.0,
        ema10=94.5,
        volume=1000.0,
        avg_volume=500.0,
        buy_target=100.0,
        strategy_type=StrategyType.AUTO,
        risk_approach=RiskApproach.CONSERVATIVE,
    )
    assert out["buy_signal"] is False
    assert out["strategy"]["decision"] == "WAIT"
    assert out["strategy"]["ml_passed"] is False
    assert any("Auto ML gate blocked" in r for r in out["rationale"])


def test_trading_signals_non_auto_ignores_ml(monkeypatch):
    monkeypatch.setenv("AUTO_ML_ENABLED", "true")
    monkeypatch.setenv("AUTO_ML_THRESHOLD", "0.99")
    monkeypatch.setenv("AUTO_ML_SHADOW_LOG", "false")

    called = {"n": 0}

    def boom(**kwargs):
        called["n"] += 1
        raise AssertionError("ML gate must not run for non-Auto")

    monkeypatch.setattr("app.services.trading_signals.apply_auto_ml_buy_gate", boom)

    rules = {
        "rsi": {"buyBelow": 40, "sellAbove": 70},
        "maChecks": {"requirePriceAboveMa200": False, "requireMa50AboveMa200": False},
        "volumeMinRatio": 0.1,
        "trendFilters": {},
        "sl": {"atrMult": 1.5, "fallbackPct": 3.0},
        "tp": {"rr": 1.5},
    }
    monkeypatch.setattr(
        "app.services.trading_signals.get_strategy_rules",
        lambda *a, **k: rules,
    )
    from app.services.trading_signals import BuyDecision, calculate_trading_signals

    monkeypatch.setattr(
        "app.services.trading_signals.should_trigger_buy_signal",
        lambda **kwargs: BuyDecision(
            should_buy=True,
            reasons=["RSI ok"],
            missing_indicators=[],
            condition_flags={"rsi_ok": True, "ma_ok": True},
        ),
    )

    out = calculate_trading_signals(
        symbol="BTC_USDT",
        price=65000.0,
        rsi=28.0,
        atr14=500.0,
        ma50=64000.0,
        ma200=60000.0,
        ema10=64500.0,
        volume=1000.0,
        avg_volume=500.0,
        buy_target=70000.0,
        strategy_type=StrategyType.SWING,
        risk_approach=RiskApproach.CONSERVATIVE,
    )
    assert called["n"] == 0
    assert out["buy_signal"] is True
