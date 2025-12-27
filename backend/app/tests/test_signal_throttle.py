import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.signal_throttle import SignalThrottleState
from app.services.signal_throttle import (
    SignalThrottleConfig,
    LastSignalSnapshot,
    should_emit_signal,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _snapshot(side: str, price: float, ts: datetime, force_next: bool = False) -> LastSignalSnapshot:
    return LastSignalSnapshot(side=side, price=price, timestamp=ts, force_next_signal=force_next)


def test_first_alert_immediate():
    cfg = SignalThrottleConfig(min_price_change_pct=1.0, min_interval_minutes=1.0)
    now = datetime.now(timezone.utc)
    allowed, reason = should_emit_signal(
        symbol="ADA_USDT",
        side="BUY",
        current_price=1.0,
        current_time=now,
        config=cfg,
        last_same_side=None,
        last_opposite_side=None,
    )
    assert allowed
    assert "No previous same-side" in reason or "First" in reason


def test_time_gate_blocks_before_price(db_session):
    cfg = SignalThrottleConfig(min_price_change_pct=1.0, min_interval_minutes=1.0)
    now = datetime.now(timezone.utc)
    last = _snapshot("BUY", price=100.0, ts=now - timedelta(seconds=30))
    allowed, reason = should_emit_signal(
        symbol="BTC_USDT",
        side="BUY",
        current_price=110.0,
        current_time=now,
        config=cfg,
        last_same_side=last,
        last_opposite_side=None,
    )
    assert not allowed
    assert "THROTTLED_TIME_GATE" in reason


def test_price_gate_applies_after_time_gate():
    cfg = SignalThrottleConfig(min_price_change_pct=5.0, min_interval_minutes=1.0)
    now = datetime.now(timezone.utc)
    last = _snapshot("BUY", price=100.0, ts=now - timedelta(seconds=120))

    allowed, reason = should_emit_signal(
        symbol="ETH_USDT",
        side="BUY",
        current_price=103.0,
        current_time=now,
        config=cfg,
        last_same_side=last,
        last_opposite_side=None,
    )
    assert not allowed
    assert "THROTTLED_PRICE_GATE" in reason

    allowed, reason = should_emit_signal(
        symbol="ETH_USDT",
        side="BUY",
        current_price=106.0,
        current_time=now,
        config=cfg,
        last_same_side=last,
        last_opposite_side=None,
    )
    assert allowed
    assert "Δt=" in reason


def test_force_next_signal_bypasses_and_clears_flag(db_session):
    now = datetime.now(timezone.utc)
    state = SignalThrottleState(
        symbol="SOL_USDT",
        strategy_key="swing:conservative",
        side="BUY",
        last_price=100.0,
        last_time=now - timedelta(seconds=10),
        force_next_signal=True,
    )
    db_session.add(state)
    db_session.commit()

    cfg = SignalThrottleConfig(min_price_change_pct=10.0, min_interval_minutes=1.0)
    allowed, reason = should_emit_signal(
        symbol="SOL_USDT",
        side="BUY",
        current_price=101.0,
        current_time=now,
        config=cfg,
        last_same_side=_snapshot("BUY", price=100.0, ts=state.last_time, force_next=True),
        last_opposite_side=None,
        db=db_session,
        strategy_key="swing:conservative",
    )
    assert allowed
    assert "IMMEDIATE_ALERT_AFTER_CONFIG_CHANGE" in reason

    refreshed = db_session.query(SignalThrottleState).filter_by(symbol="SOL_USDT").first()
    assert refreshed is not None
    assert refreshed.force_next_signal is False


def test_per_side_independent_throttle():
    cfg = SignalThrottleConfig(min_price_change_pct=1.0, min_interval_minutes=1.0)
    now = datetime.now(timezone.utc)
    last_buy = _snapshot("BUY", price=100.0, ts=now - timedelta(seconds=10))

    # BUY should be throttled by time gate
    allowed_buy, reason_buy = should_emit_signal(
        symbol="DOT_USDT",
        side="BUY",
        current_price=101.0,
        current_time=now,
        config=cfg,
        last_same_side=last_buy,
        last_opposite_side=None,
    )
    assert not allowed_buy
    assert "THROTTLED_TIME_GATE" in reason_buy

    # SELL side has no history, so it should be allowed immediately
    allowed_sell, reason_sell = should_emit_signal(
        symbol="DOT_USDT",
        side="SELL",
        current_price=101.0,
        current_time=now,
        config=cfg,
        last_same_side=None,
        last_opposite_side=last_buy,
    )
    assert allowed_sell
    assert "First" in reason_sell or "No previous" in reason_sell
