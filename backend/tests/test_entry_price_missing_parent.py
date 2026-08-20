"""Regresión: SUI_USD 2026-08-20.

El TP se ejecutó y notificó a las 09:00:46 UTC, pero la orden de entrada
(el padre) no se persistió en exchange_orders hasta las 09:03:26. El lookup
no encontró al padre y cayó al heurístico, que devolvió el entry price de la
posición ANTERIOR (ya cerrada, 18-ago, $0.65737) → el mensaje reportó
"LOSS REALIZED -$86.51 (-9.53%)" en un trade que ganó +$5.08.

Con parent_order_id conocido pero padre ausente, debe devolver None.
"""
import types

import pytest

from app.services.exchange_sync import ExchangeSyncService


class _QueryParentMissing:
    def filter(self, *a, **k):
        return self

    def first(self):
        return None

    def order_by(self, *a, **k):
        raise AssertionError(
            "No debe caer al heuristico: tomaria el entry de una posicion cerrada"
        )


class _QueryParentFound:
    def __init__(self, parent):
        self._parent = parent

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._parent


class _FakeDB:
    def __init__(self, query_obj):
        self._q = query_obj

    def query(self, *a, **k):
        return self._q


def _tp_order():
    return types.SimpleNamespace(
        parent_order_id="5755600493236591341",
        exchange_order_id="73817490102104603",
        symbol="SUI_USD",
        side="BUY",
        exchange_create_time=None,
    )


def _svc():
    return object.__new__(ExchangeSyncService)


def test_padre_no_sincronizado_devuelve_none():
    resultado = _svc()._lookup_entry_price_for_protection(
        _FakeDB(_QueryParentMissing()), _tp_order()
    )
    assert resultado is None


def test_padre_presente_devuelve_su_precio():
    padre = types.SimpleNamespace(avg_price=0.72368, price=0.72368)
    resultado = _svc()._lookup_entry_price_for_protection(
        _FakeDB(_QueryParentFound(padre)), _tp_order()
    )
    assert resultado == pytest.approx(0.72368)
