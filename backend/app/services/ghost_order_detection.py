"""Seleccion de candidatos a "ghost order" para el dashboard.

Un ghost es una fila que la base de datos cree ABIERTA mientras el
exchange no la reporta entre sus ordenes abiertas. Las filas terminales
(FILLED, CANCELLED, REJECTED, EXPIRED) son historial y nunca son ghosts.

Este modulo existe porque la consulta inline anterior del dashboard
anadia ``OR order_role IN (SL, TP) OR order_type IN (...)``, lo que
arrastraba las 500 filas SL/TP mas recientes fuera cual fuera su status
y reportaba ~498 ghosts falsos con la base de datos limpia (veredicto
23-ago-2026: las filas realmente abiertas eran 7 y coincidian 1:1 con el
exchange).
"""

from typing import Iterable, List, Set

from app.models.exchange_order import ExchangeOrder, OrderStatusEnum

# Solo estos estados son candidatos a ghost. Debe coincidir con la
# definicion de "abierta" del detector de routes_orders.py.
OPEN_STATUSES = [
    OrderStatusEnum.NEW,
    OrderStatusEnum.ACTIVE,
    OrderStatusEnum.PARTIALLY_FILLED,
]


def query_open_db_orders(db, limit: int = 500):
    """Filas que la DB cree abiertas — los UNICOS candidatos a ghost."""
    from sqlalchemy import func

    return (
        db.query(ExchangeOrder)
        .filter(ExchangeOrder.status.in_(OPEN_STATUSES))
        .order_by(
            func.coalesce(
                ExchangeOrder.exchange_create_time, ExchangeOrder.created_at
            ).desc()
        )
        .limit(limit)
        .all()
    )


def find_ghost_orders(db_orders: Iterable, cached_order_ids: Set[str]) -> List[dict]:
    """Filas abiertas en DB que el exchange no reporta como abiertas."""
    ghosts: List[dict] = []
    for db_order in db_orders:
        order_id_str = str(db_order.exchange_order_id)
        if order_id_str not in cached_order_ids:
            ghosts.append(
                {
                    "order_id": order_id_str,
                    "symbol": db_order.symbol,
                    "status": db_order.status.value
                    if hasattr(db_order.status, "value")
                    else str(db_order.status),
                    "side": db_order.side.value
                    if hasattr(db_order.side, "value")
                    else str(db_order.side),
                }
            )
    return ghosts
