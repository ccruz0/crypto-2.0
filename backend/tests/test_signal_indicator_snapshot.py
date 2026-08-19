"""One row per emitted signal, and never one per evaluation.

Nothing recorded what the market looked like when a signal fired: orders keep
price and quantity, and watchlist_signal_state is keyed on symbol so every
evaluation overwrites the last. That made "which indicator combination produced
the entries that worked?" unanswerable from stored data.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.signal_indicator_snapshot import SignalIndicatorSnapshot


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine, tables=[SignalIndicatorSnapshot.__table__])
    s = Session()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine, tables=[SignalIndicatorSnapshot.__table__])
        engine.dispose()


class _Monitor:
    """Just the helper under test, without booting the whole SignalMonitor."""

    from app.services.signal_monitor import SignalMonitorService
    _record_signal_snapshot = SignalMonitorService._record_signal_snapshot


def _indicators():
    return {
        "price": 64276.46, "rsi": 23.56, "ma200": 63603.96,
        "ma50": 64217.69, "ema10": 64425.06, "atr": 200.24,
        "volume_ratio": 0.76, "rsi_buy_below": 30, "volume_min_ratio": 1,
    }


def _state():
    return {
        "strategy_key": "auto:conservative",
        "reasons": {
            "buy_rsi_ok": True, "buy_ma_ok": False,
            "buy_trend_filters_ok": True,
            "buy_rsi_confirmation_ok": None,
            "buy_candle_confirmation_ok": None,
        },
    }


def test_emitted_signal_is_recorded_with_market_state(db_session):
    _Monitor()._record_signal_snapshot(
        db_session, symbol="BTC_USD", side="BUY",
        strategy_state=_state(), indicators=_indicators(),
        correlation_id="abc123",
    )
    rows = db_session.query(SignalIndicatorSnapshot).all()
    assert len(rows) == 1
    r = rows[0]
    assert r.symbol == "BTC_USD" and r.side == "BUY"
    assert r.rsi == pytest.approx(23.56)
    assert r.ma50 == pytest.approx(64217.69) and r.ema10 == pytest.approx(64425.06)
    # The thresholds actually applied: presets are edited in place with no audit
    # trail, so the key alone would not let anyone reconstruct the decision.
    assert r.rsi_buy_below == pytest.approx(30)
    assert r.volume_min_ratio == pytest.approx(1)
    # The verdict as it was taken, preserved against later rule changes.
    assert r.rsi_ok is True and r.ma_ok is False and r.trend_filters_ok is True
    assert r.correlation_id == "abc123"


@pytest.mark.parametrize("side", ["NONE", "WAIT", None, ""])
def test_non_signals_are_not_recorded(db_session, side):
    """The bounded-growth guarantee: ~29 symbols per cycle must not land here."""
    _Monitor()._record_signal_snapshot(
        db_session, symbol="BTC_USD", side=side,
        strategy_state=_state(), indicators=_indicators(),
    )
    assert db_session.query(SignalIndicatorSnapshot).count() == 0


def test_rows_accumulate_instead_of_overwriting(db_session):
    """Append-only: this is the whole point versus watchlist_signal_state."""
    for rsi in (28.0, 24.0, 21.0):
        ind = _indicators(); ind["rsi"] = rsi
        _Monitor()._record_signal_snapshot(
            db_session, symbol="BTC_USD", side="BUY",
            strategy_state=_state(), indicators=ind,
        )
    rows = db_session.query(SignalIndicatorSnapshot).order_by(
        SignalIndicatorSnapshot.id).all()
    assert [r.rsi for r in rows] == [28.0, 24.0, 21.0]


def test_never_raises_on_bad_input(db_session):
    """A diagnostics table must not be able to block a trade."""
    _Monitor()._record_signal_snapshot(
        db_session, symbol="BTC_USD", side="BUY",
        strategy_state=None, indicators={"rsi": "no-es-un-numero", "price": None},
    )
    rows = db_session.query(SignalIndicatorSnapshot).all()
    assert len(rows) == 1
    assert rows[0].rsi is None and rows[0].price is None


def test_helper_is_actually_wired_into_the_evaluation_loop():
    """El helper existia pero no lo llamaba nadie: registraba cero de cero presets.

    Es el mismo modo de fallo que ghost_mixed_trimmed (#505): codigo correcto
    que nunca se ejecuta. Este test fija que el punto de llamada existe.
    """
    import inspect
    from app.services import signal_monitor as sm

    src = inspect.getsource(sm)
    llamadas = src.count("self._record_signal_snapshot(")
    assert llamadas >= 1, "el snapshot no se invoca desde el bucle de evaluacion"


def test_call_site_is_preset_agnostic():
    """Debe colgar del upsert canonico de estado, que recorre TODOS los simbolos.

    Si colgara de una rama especifica de `auto`, los presets que si emiten
    quedarian sin registrar — que es justo el dato que hace falta.
    """
    import inspect
    from app.services import signal_monitor as sm

    src = inspect.getsource(sm)
    idx = src.index("self._record_signal_snapshot(")
    ventana = src[max(0, idx - 2000):idx]
    # El upsert canonico persiste el estado de cada simbolo en cada vuelta.
    assert "_upsert_watchlist_signal_state(" in ventana
    # Y no debe estar dentro de un filtro por preset.
    assert 'strategy_key == "auto"' not in ventana
    assert "startswith('auto')" not in ventana
