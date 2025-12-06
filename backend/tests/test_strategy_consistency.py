from app.services import trading_signals
from app.services.strategy_profiles import StrategyType, RiskApproach


def _fake_rules(rsi_buy: float, volume_ratio: float):
    return {
        "rsi": {"buyBelow": rsi_buy, "sellAbove": 70},
        "maChecks": {"ma50": False, "ema10": False, "ma200": False},
        "volumeMinRatio": volume_ratio,
    }


def _patch_rules(monkeypatch, buy_threshold: float, volume_ratio: float):
    monkeypatch.setattr(
        trading_signals,
        "get_strategy_rules",
        lambda preset, risk: _fake_rules(buy_threshold, volume_ratio),
    )


def _base_signal_kwargs():
    return dict(
        symbol="TEST",
        price=1.0,
        rsi=50.36,
        atr14=0.1,
        ma50=1.0,
        ma200=0.8,
        ema10=0.9,
        ma10w=0.95,
        resistance_up=1.03,
        buy_target=None,
        last_buy_price=None,
        position_size_usd=100.0,
        rsi_buy_threshold=40,
        rsi_sell_threshold=70,
        strategy_type=StrategyType.SCALP,
        risk_approach=RiskApproach.AGGRESSIVE,
    )


def test_strategy_decision_buy_when_rsi_and_volume_ok(monkeypatch):
    _patch_rules(monkeypatch, buy_threshold=55, volume_ratio=1.0)
    kwargs = _base_signal_kwargs()
    result = trading_signals.calculate_trading_signals(
        volume=110,
        avg_volume=100,
        **kwargs,
    )
    strategy = result.get("strategy", {})
    assert strategy.get("decision") == "BUY"
    reasons = strategy.get("reasons", {})
    assert reasons.get("buy_rsi_ok") is True
    assert reasons.get("buy_volume_ok") is True


def test_strategy_decision_wait_when_volume_low(monkeypatch):
    _patch_rules(monkeypatch, buy_threshold=55, volume_ratio=1.0)
    kwargs = _base_signal_kwargs()
    result = trading_signals.calculate_trading_signals(
        volume=50,
        avg_volume=100,
        **kwargs,
    )
    strategy = result.get("strategy", {})
    assert strategy.get("decision") == "WAIT"
    reasons = strategy.get("reasons", {})
    assert reasons.get("buy_volume_ok") is False

