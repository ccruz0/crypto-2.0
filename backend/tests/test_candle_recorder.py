"""Tests del registro historico de velas.

Lo que se prueba es lo que puede romper en silencio: que no duplique al
reejecutar, que descarte velas invalidas en vez de guardarlas, y que un
simbolo que falla no aborte el barrido.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.services import candle_recorder as cr


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def _payload(rows):
    return {"result": {"data": rows}}


def test_fetch_normaliza_y_ordena():
    rows = [
        {"t": 3000, "o": "3", "h": "3.5", "l": "2.5", "c": "3.2", "v": "10"},
        {"t": 1000, "o": "1", "h": "1.5", "l": "0.5", "c": "1.2", "v": "20"},
    ]
    with patch.object(cr, "http_get", return_value=_Resp(200, _payload(rows))):
        out = cr.fetch_candles("BTC_USD", "1h")
    assert [c["open_time"] for c in out] == [1000, 3000]
    assert out[0]["close"] == 1.2
    assert out[1]["volume"] == 10.0


def test_fetch_descarta_velas_con_precio_cero():
    """Una vela a cero es un hueco del exchange, no una caida del 100%."""
    rows = [
        {"t": 1000, "o": "1", "h": "1.5", "l": "0.5", "c": "1.2", "v": "1"},
        {"t": 2000, "o": "0", "h": "0", "l": "0", "c": "0", "v": "0"},
    ]
    with patch.object(cr, "http_get", return_value=_Resp(200, _payload(rows))):
        out = cr.fetch_candles("BTC_USD", "1h")
    assert len(out) == 1
    assert out[0]["open_time"] == 1000


def test_fetch_descarta_fila_malformada_sin_perder_el_resto():
    rows = [
        {"t": 1000, "o": "1", "h": "1.5", "l": "0.5", "c": "1.2"},
        {"t": 2000, "o": "x"},  # malformada
    ]
    with patch.object(cr, "http_get", return_value=_Resp(200, _payload(rows))):
        out = cr.fetch_candles("BTC_USD", "1h")
    assert len(out) == 1


def test_fetch_devuelve_lista_vacia_si_http_falla():
    with patch.object(cr, "http_get", return_value=_Resp(500, {})):
        assert cr.fetch_candles("BTC_USD", "1h") == []


def test_fetch_devuelve_lista_vacia_si_excepcion():
    with patch.object(cr, "http_get", side_effect=RuntimeError("red caida")):
        assert cr.fetch_candles("BTC_USD", "1h") == []


def test_store_no_escribe_si_no_hay_velas():
    db = MagicMock()
    assert cr.store_candles(db, "BTC_USD", "1h", []) == 0
    db.execute.assert_not_called()


def test_store_usa_on_conflict_do_nothing():
    """La idempotencia la impone la BD; si esto se pierde, se duplican filas."""
    db = MagicMock()
    db.execute.return_value = MagicMock(rowcount=2)
    n = cr.store_candles(db, "BTC_USD", "1h", [
        {"open_time": 1, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 3},
        {"open_time": 2, "open": 1, "high": 2, "low": 0.5, "close": 1.6, "volume": 4},
    ])
    assert n == 2
    stmt = db.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "ON CONFLICT" in compiled.upper()
    assert "DO NOTHING" in compiled.upper()
    db.commit.assert_called_once()


def test_record_all_continua_si_un_simbolo_falla():
    db = MagicMock()
    def _side(_db, symbol, tf, count=300):
        if symbol == "MALO":
            raise RuntimeError("boom")
        return 5
    with patch.object(cr, "record_symbol", side_effect=_side):
        totals = cr.record_all(db, ["BUENO", "MALO", "OTRO"], timeframes=["1h"])
    assert totals["1h"] == 10   # los dos buenos, el malo no aborta
    db.rollback.assert_called_once()
