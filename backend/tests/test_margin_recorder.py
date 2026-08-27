"""Tests del registro de margen.

Control negativo: todos estos fallan sobre main sin el cambio, porque ni el
modelo MarginSnapshot ni el servicio margin_recorder existen alli.
"""
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.margin_snapshot import MarginSnapshot
from app.models.portfolio_loan import PortfolioLoan
from app.services import margin_recorder as mr


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[MarginSnapshot.__table__, PortfolioLoan.__table__],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _equity(valor):
    """Parchea la lectura del exchange con (equity, exposure, daily_pct)."""
    cliente = MagicMock()
    cliente.get_equity_from_user_balance.return_value = valor
    modulo = MagicMock()
    modulo.trade_client = cliente
    return patch.dict(
        "sys.modules", {"app.services.brokers.crypto_com_trade": modulo}
    )


def test_guarda_equity_y_exposicion(db):
    with _equity((1000.0, 250.0, 0.0)):
        fila = mr.record_margin_snapshot(db)
    assert fila is not None
    assert fila.equity == 1000.0
    assert fila.exposure == 250.0
    assert db.query(MarginSnapshot).count() == 1


def test_calcula_margen_libre_y_ratio(db):
    with _equity((1000.0, 250.0, 0.0)):
        fila = mr.record_margin_snapshot(db)
    assert fila.free_margin == 750.0
    assert fila.margin_ratio == pytest.approx(0.25)


def test_sin_equity_el_ratio_es_nulo_no_cero(db):
    """Un ratio de 0 significaria 'sin exposicion'. Aqui es 'no se sabe'."""
    with _equity((0.0, 120.0, 0.0)):
        fila = mr.record_margin_snapshot(db)
    assert fila.margin_ratio is None
    assert fila.free_margin == -120.0


def test_si_el_exchange_falla_no_escribe_fila(db):
    """Una fila de ceros seria indistinguible de una cuenta vacia real."""
    cliente = MagicMock()
    cliente.get_equity_from_user_balance.side_effect = ValueError("caido")
    modulo = MagicMock()
    modulo.trade_client = cliente
    with patch.dict("sys.modules", {"app.services.brokers.crypto_com_trade": modulo}):
        assert mr.record_margin_snapshot(db) is None
    assert db.query(MarginSnapshot).count() == 0


def test_agrega_la_deuda_viva(db):
    db.add(PortfolioLoan(currency="BONK", borrowed_amount=1, borrowed_usd_value=123.91, is_active=True))
    db.add(PortfolioLoan(currency="USDT", borrowed_amount=1, borrowed_usd_value=26.09, is_active=True))
    db.add(PortfolioLoan(currency="VIEJA", borrowed_amount=1, borrowed_usd_value=999.0, is_active=False))
    db.commit()
    with _equity((1000.0, 250.0, 0.0)):
        fila = mr.record_margin_snapshot(db)
    assert fila.borrowed_usd == pytest.approx(150.0)


def test_sin_prestamos_la_deuda_es_cero_no_nula(db):
    with _equity((1000.0, 0.0, 0.0)):
        fila = mr.record_margin_snapshot(db)
    assert fila.borrowed_usd == 0.0


def test_acumula_serie_temporal(db):
    """El sentido de la tabla: varias muestras, no un unico valor."""
    for eq, ex in ((1000.0, 100.0), (900.0, 300.0), (800.0, 600.0)):
        with _equity((eq, ex, 0.0)):
            mr.record_margin_snapshot(db)
    filas = db.query(MarginSnapshot).order_by(MarginSnapshot.id).all()
    assert [f.equity for f in filas] == [1000.0, 900.0, 800.0]
    assert [f.free_margin for f in filas] == [900.0, 600.0, 200.0]
    assert filas[-1].margin_ratio == pytest.approx(0.75)
