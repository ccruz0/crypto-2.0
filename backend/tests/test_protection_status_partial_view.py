"""Regresion: una vista parcial del exchange no debe reportar la otra pata como ausente.

_get_protection_status consultaba el exchange en vivo y devolvia en cuanto veia
UNA de las dos protecciones (`if has_sl or has_tp`), sin llegar al respaldo de la
base de datos que tenia el dato completo.

Caso BONK_USD, 24-ago-2026: la revision diaria envio "🛑 Stop Loss: ❌ Falta /
🚀 Take Profit: ✅ Activo" mientras exchange_orders tenia el STOP_LOSS en ACTIVE
(creado el 20-ago). El fetch en vivo perdio esa pata y el early-return impidio
consultar la DB.

El fallback protegia contra "no veo nada" pero no contra "veo la mitad".
"""
import pytest

from app.services import position_review_service as prs


class _FakeQuery:
    def __init__(self, n):
        self._n = n

    def filter(self, *a, **k):
        return self

    def count(self):
        return self._n


class _FakeDB:
    """Devuelve 1 para la consulta de SL y 0 para la de TP, en ese orden."""

    def __init__(self, counts):
        self._counts = list(counts)

    def query(self, *a, **k):
        return _FakeQuery(self._counts.pop(0) if self._counts else 0)


def _sin_fetch_en_vivo(monkeypatch, has_sl, has_tp):
    """Simula el fetch en vivo devolviendo solo las patas indicadas."""
    orders = []
    if has_sl:
        orders.append({"instrument_name": "BONK_USD", "order_type": "STOP_LIMIT",
                       "order_status": "ACTIVE"})
    if has_tp:
        orders.append({"instrument_name": "BONK_USD", "order_type": "TAKE_PROFIT_LIMIT",
                       "order_status": "ACTIVE"})

    import sys
    import types
    mod = types.ModuleType("app.services.unified_open_orders_fetch")
    mod.fetch_unified_open_orders = lambda: {"all_raw_orders": orders}
    monkeypatch.setitem(sys.modules, "app.services.unified_open_orders_fetch", mod)


def test_vista_parcial_consulta_la_db(monkeypatch):
    """El exchange solo ve el TP; la DB tiene el SL -> ambas deben salir True."""
    _sin_fetch_en_vivo(monkeypatch, has_sl=False, has_tp=True)
    db = _FakeDB([1, 1])  # DB: 1 SL activo, 1 TP activo
    out = prs._get_protection_status(db, "BONK_USD")
    assert out["has_sl"] is True, (
        "Con vista parcial del exchange hay que consultar la DB; "
        "reportar 'SL falta' teniendolo en la DB es el bug de BONK_USD"
    )
    assert out["has_tp"] is True


def test_vista_completa_no_consulta_la_db(monkeypatch):
    """Si el exchange ve ambas, se devuelve sin tocar la DB."""
    _sin_fetch_en_vivo(monkeypatch, has_sl=True, has_tp=True)

    class _ExplotaDB:
        def query(self, *a, **k):
            raise AssertionError("no debe consultarse la DB si el exchange ve ambas")

    out = prs._get_protection_status(_ExplotaDB(), "BONK_USD")
    assert out == {"has_sl": True, "has_tp": True}


def test_exchange_ve_una_db_no_ve_ninguna(monkeypatch):
    """Lo que ve el exchange no se pierde al combinar con la DB."""
    _sin_fetch_en_vivo(monkeypatch, has_sl=False, has_tp=True)
    db = _FakeDB([0, 0])
    out = prs._get_protection_status(db, "BONK_USD")
    assert out["has_tp"] is True, "el TP visto en vivo no puede perderse"
    assert out["has_sl"] is False
