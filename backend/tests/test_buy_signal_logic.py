import pytest

from app.services.strategy_profiles import StrategyType, RiskApproach
from app.services.trading_signals import should_trigger_buy_signal


CASES = [
    {
        "id": "swing_conservative",
        "strategy": StrategyType.SWING,
        "approach": RiskApproach.CONSERVATIVE,
        "positive": dict(price=105, rsi=30, ma200=100, ma50=103, ema10=101),
        "negative": dict(price=95, rsi=30, ma200=100, ma50=103, ema10=101),
    },
    {
        "id": "swing_aggressive",
        "strategy": StrategyType.SWING,
        "approach": RiskApproach.AGGRESSIVE,
        "positive": dict(price=102, rsi=40, ma200=100, ma50=99, ema10=98),
        "negative": dict(price=102, rsi=50, ma200=100, ma50=99, ema10=98),
    },
    {
        "id": "intraday_conservative",
        "strategy": StrategyType.INTRADAY,
        "approach": RiskApproach.CONSERVATIVE,
        "positive": dict(price=120, rsi=35, ma200=110, ma50=115, ema10=113),
        "negative": dict(price=105, rsi=35, ma200=110, ma50=115, ema10=113),
    },
    {
        "id": "intraday_aggressive",
        "strategy": StrategyType.INTRADAY,
        "approach": RiskApproach.AGGRESSIVE,
        "positive": dict(price=104, rsi=45, ma200=110, ma50=106, ema10=102),
        "negative": dict(price=90, rsi=45, ma200=110, ma50=106, ema10=102),
    },
    {
        "id": "scalp_conservative",
        "strategy": StrategyType.SCALP,
        "approach": RiskApproach.CONSERVATIVE,
        "positive": dict(price=101, rsi=40, ma200=120, ma50=102, ema10=99),
        "negative": dict(price=96, rsi=40, ma200=120, ma50=102, ema10=99),
    },
    {
        "id": "scalp_aggressive",
        "strategy": StrategyType.SCALP,
        "approach": RiskApproach.AGGRESSIVE,
        "positive": dict(price=100, rsi=50, ma200=110, ma50=105, ema10=101),
        "negative": dict(price=95, rsi=50, ma200=110, ma50=105, ema10=101),
    },
]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_should_trigger_buy_signal_true(case):
    decision = should_trigger_buy_signal(
        symbol="TEST",
        strategy_type=case["strategy"],
        risk_approach=case["approach"],
        **case["positive"],
    )
    assert decision.should_buy, f"Expected BUY for {case['id']}, got reasons: {decision.reasons}"


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_should_trigger_buy_signal_false(case):
    decision = should_trigger_buy_signal(
        symbol="TEST",
        strategy_type=case["strategy"],
        risk_approach=case["approach"],
        **case["negative"],
    )
    assert decision.should_buy is False, f"Expected NO BUY for {case['id']}"


def test_should_trigger_buy_signal_missing_indicators_blocks():
    decision = should_trigger_buy_signal(
        symbol="TEST",
        price=110,
        rsi=30,
        ma200=100,
        ma50=None,
        ema10=105,
        strategy_type=StrategyType.SWING,
        risk_approach=RiskApproach.CONSERVATIVE,
    )
    assert decision.should_buy is False
    assert "MA50" in decision.missing_indicators


def test_should_trigger_buy_signal_requires_ema10():
    decision = should_trigger_buy_signal(
        symbol="TEST",
        price=110,
        rsi=30,
        ma200=100,
        ma50=102,
        ema10=None,
        strategy_type=StrategyType.SWING,
        risk_approach=RiskApproach.AGGRESSIVE,
    )
    assert decision.should_buy is False


