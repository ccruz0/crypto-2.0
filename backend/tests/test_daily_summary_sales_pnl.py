"""El Reporte de Ventas no puede inventar P&L.

Regresion del 29/30-ago-2026: 4 aperturas de CORTO de mercado (~$100)
reportadas como ventas con perdida de -$16,62 contra compras viejas sin
relacion, via el fallback "compra FILLED mas reciente del simbolo". Mismo
antipatron que el -$86,51 ya corregido en exchange_sync (:1502-1507).
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.daily_summary import DailySummaryService

NOW = datetime.now(timezone.utc)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[ExchangeOrder.__table__])
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine, tables=[ExchangeOrder.__table__])
        engine.dispose()


def _order(db, oid, side, *, role=None, otype="MARKET", price=1.0, qty=100.0,
           parent=None, hours_ago=1.0, symbol="APT_USD", status=OrderStatusEnum.FILLED):
    ts = NOW - timedelta(hours=hours_ago)
    o = ExchangeOrder(
        exchange_order_id=oid, symbol=symbol, side=side, order_type=otype,
        status=status, price=price, avg_price=price, quantity=qty,
        cumulative_quantity=qty, order_role=role, parent_order_id=parent,
        exchange_create_time=ts, exchange_update_time=ts, created_at=ts,
    )
    db.add(o)
    db.commit()
    return o


def _run_report(db):
    svc = DailySummaryService()
    svc.telegram = MagicMock()
    svc.telegram.send_message.return_value = True
    svc.send_sell_orders_report(db=db)
    assert svc.telegram.send_message.called
    return svc.telegram.send_message.call_args[0][0]


class TestShortEntryNoFabricatedPnl:
    def test_short_entry_reports_no_pnl_even_with_old_buy_nearby(self, db_session):
        """El caso del 29-ago: SELL de mercado sin padre = apertura de corto.

        Con una compra vieja del mismo simbolo en la tabla, el informe
        anterior fabricaba P&L contra ella. Ahora: etiqueta de apertura,
        cero P&L, y la compra vieja ni se consulta.
        """
        _order(db_session, "old-buy", OrderSideEnum.BUY, price=0.60, hours_ago=48)
        _order(db_session, "short-entry", OrderSideEnum.SELL, price=0.54, qty=183.35, hours_ago=5)

        msg = _run_report(db_session)
        assert "Apertura de CORTO" in msg
        assert "P&L Total" not in msg and "P&L realizado" not in msg
        assert "$0.60" not in msg  # la compra vieja no aparece como "entrada"
        assert "Aperturas de corto: 1" in msg

    def test_sltp_close_with_real_parent_gets_pnl(self, db_session):
        entry = _order(db_session, "buy-e", OrderSideEnum.BUY, price=1.00, qty=100.0, hours_ago=30)
        _order(db_session, "tp-c", OrderSideEnum.SELL, role="TAKE_PROFIT",
               otype="TAKE_PROFIT_LIMIT", price=1.03, qty=100.0, parent="buy-e", hours_ago=2)

        msg = _run_report(db_session)
        assert "P&L: +$3.00" in msg
        assert "Entrada: $1" in msg
        assert "Cierres con P&L: 1/1" in msg

    def test_unlinked_protection_close_never_guesses(self, db_session):
        """SL sin padre: antes cogia 'la compra mas reciente'. Ahora, honestidad."""
        _order(db_session, "unrelated-buy", OrderSideEnum.BUY, price=2.00, hours_ago=20)
        _order(db_session, "sl-orphan", OrderSideEnum.SELL, role="STOP_LOSS",
               otype="STOP_LIMIT", price=0.97, qty=50.0, hours_ago=3)

        msg = _run_report(db_session)
        assert "cierre sin vinculo" in msg
        assert "P&L:" not in msg.replace("Sin P&L", "")
        assert "$2" not in msg

    def test_quantity_mismatch_marks_dubious_link(self, db_session):
        """Padre BUY con cantidad 10x distinta: la firma del parent adivinado
        por exchange_sync (:2403-2431). Sin P&L, con motivo."""
        _order(db_session, "buy-big", OrderSideEnum.BUY, price=1.00, qty=1000.0, hours_ago=10)
        _order(db_session, "sl-linked", OrderSideEnum.SELL, role="STOP_LOSS",
               otype="STOP_LIMIT", price=0.95, qty=100.0, parent="buy-big", hours_ago=1)

        msg = _run_report(db_session)
        assert "vinculo dudoso" in msg
        assert "P&L: -$" not in msg

    def test_parent_missing_row_is_pending_not_guessed(self, db_session):
        _order(db_session, "tp-race", OrderSideEnum.SELL, role="TAKE_PROFIT",
               otype="TAKE_PROFIT_LIMIT", price=1.10, qty=10.0,
               parent="not-synced-yet", hours_ago=1)
        msg = _run_report(db_session)
        assert "entrada aun no sincronizada" in msg

    def test_stub_rows_are_skipped(self, db_session):
        _order(db_session, "STUB-CLOSED-XYZ-1", OrderSideEnum.SELL,
               role="STOP_LOSS", otype="STOP_LIMIT", price=1.0, qty=5.0, hours_ago=2)
        svc = DailySummaryService()
        svc.telegram = MagicMock()
        svc.telegram.send_message.return_value = True
        svc.send_sell_orders_report(db=db_session)
        msg = svc.telegram.send_message.call_args[0][0]
        assert "STUB-CLOSED" not in msg

    def test_weighted_average_not_arithmetic(self, db_session):
        """-5% en $20 y +1% en $1000 no es -2%: es +0.59% ponderado."""
        _order(db_session, "b1", OrderSideEnum.BUY, price=1.00, qty=20.0, hours_ago=30, symbol="AAA_USD")
        _order(db_session, "s1", OrderSideEnum.SELL, role="STOP_LOSS", otype="STOP_LIMIT",
               price=0.95, qty=20.0, parent="b1", hours_ago=2, symbol="AAA_USD")
        _order(db_session, "b2", OrderSideEnum.BUY, price=10.00, qty=100.0, hours_ago=28, symbol="BBB_USD")
        _order(db_session, "s2", OrderSideEnum.SELL, role="TAKE_PROFIT", otype="TAKE_PROFIT_LIMIT",
               price=10.10, qty=100.0, parent="b2", hours_ago=2, symbol="BBB_USD")

        msg = _run_report(db_session)
        # pnl = -1 + 10 = +9 sobre entrada 20+1000=1020 -> +0.88%
        assert "P&L realizado (cierres): +$9.00" in msg
        assert "+0.88%" in msg
