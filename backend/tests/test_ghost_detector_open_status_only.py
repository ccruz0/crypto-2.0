"""El detector de ghost orders solo debe considerar filas ABIERTAS.

Bug real (23-ago-2026): la consulta del dashboard incluia
``OR order_role IN (SL, TP) OR order_type IN (...)``, arrastrando las
500 filas SL/TP mas recientes (mayoria FILLED/CANCELLED) y reportando
~498 ghosts falsos con la base de datos limpia (7 abiertas = 7 en el
exchange, coincidencia 1:1).
"""

from unittest.mock import MagicMock

from app.models.exchange_order import OrderStatusEnum
from app.services.ghost_order_detection import (
    OPEN_STATUSES,
    find_ghost_orders,
    query_open_db_orders,
)


class _Row:
    def __init__(self, oid, symbol="BTC_USDT", status=OrderStatusEnum.ACTIVE, side="SELL"):
        self.exchange_order_id = oid
        self.symbol = symbol
        self.status = status
        self.side = side


def test_open_statuses_are_exactly_the_open_states():
    assert set(OPEN_STATUSES) == {
        OrderStatusEnum.NEW,
        OrderStatusEnum.ACTIVE,
        OrderStatusEnum.PARTIALLY_FILLED,
    }


def test_query_filters_by_open_status_only():
    db = MagicMock()
    query_open_db_orders(db)
    (criterion,) = db.query.return_value.filter.call_args.args
    text = str(criterion)
    assert "status IN" in text
    # La regresion original: el filtro incluia order_role/order_type y
    # convertia historial terminal en "ghosts".
    assert "order_role" not in text
    assert "order_type" not in text


def test_find_ghost_orders_flags_only_rows_missing_on_exchange():
    rows = [_Row("111"), _Row("222", symbol="BONK_USD")]
    ghosts = find_ghost_orders(rows, cached_order_ids={"111"})
    assert [g["order_id"] for g in ghosts] == ["222"]
    assert ghosts[0]["symbol"] == "BONK_USD"
    assert ghosts[0]["status"] == OrderStatusEnum.ACTIVE.value
    assert ghosts[0]["side"] == "SELL"


def test_no_ghosts_when_db_matches_exchange():
    rows = [_Row("1"), _Row("2")]
    assert find_ghost_orders(rows, {"1", "2"}) == []
