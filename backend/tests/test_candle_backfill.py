"""Tests del relleno historico paginado (end_ts).

Control negativo deliberado: los tres tests de paginacion fallan sobre `main`
sin este cambio, porque `fetch_candles` no acepta `end_ts` y `backfill_symbol`
no existe. Si pasan sin el parche, el test no esta midiendo lo que dice.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.services import candle_recorder as cr


def _resp(rows):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"result": {"data": rows}}
    return r


def _candle(t, price=100.0):
    return {"t": t, "o": price, "h": price, "l": price, "c": price, "v": 1.0}


def test_fetch_candles_no_manda_end_ts_si_no_se_pide():
    with patch.object(cr, "http_get", return_value=_resp([_candle(1000)])) as g:
        cr.fetch_candles("BTC_USD", "1D")
    assert "end_ts" not in g.call_args.kwargs["params"]


def test_fetch_candles_manda_end_ts_como_entero():
    with patch.object(cr, "http_get", return_value=_resp([_candle(1000)])) as g:
        cr.fetch_candles("BTC_USD", "1D", end_ts=1777248000000)
    assert g.call_args.kwargs["params"]["end_ts"] == 1777248000000


def test_backfill_pagina_hacia_atras_y_para_al_agotarse():
    """Tres paginas que retroceden y una cuarta que repite: debe parar en la 4a."""
    paginas = [
        [_candle(3000), _candle(3100)],
        [_candle(2000), _candle(2100)],
        [_candle(1000), _candle(1100)],
        [_candle(1000), _candle(1100)],   # no retrocede -> corta
    ]
    llamadas = []

    def fake(symbol, timeframe, count=cr.MAX_COUNT, end_ts=None, timeout=15.0):
        llamadas.append(end_ts)
        return [
            {"open_time": c["t"], "open": 1.0, "high": 1.0, "low": 1.0,
             "close": 1.0, "volume": 1.0}
            for c in paginas[min(len(llamadas) - 1, len(paginas) - 1)]
        ]

    db = MagicMock()
    with patch.object(cr, "fetch_candles", side_effect=fake), \
         patch.object(cr, "store_candles", return_value=2):
        total = cr.backfill_symbol(db, "BTC_USD", "1D")

    assert llamadas[0] is None
    assert llamadas[1] == 2999
    assert llamadas[2] == 1999
    assert len(llamadas) == 4
    assert total == 6


def test_backfill_respeta_el_tope_de_paginas():
    """Una API que siempre retrocede no puede girar para siempre."""
    n = {"i": 0}

    def fake(symbol, timeframe, count=cr.MAX_COUNT, end_ts=None, timeout=15.0):
        n["i"] += 1
        base = 10_000_000 - n["i"] * 1000
        return [{"open_time": base, "open": 1.0, "high": 1.0, "low": 1.0,
                 "close": 1.0, "volume": 1.0}]

    db = MagicMock()
    with patch.object(cr, "fetch_candles", side_effect=fake), \
         patch.object(cr, "store_candles", return_value=1):
        cr.backfill_symbol(db, "BTC_USD", "1D", max_pages=5)

    assert n["i"] == 5


def test_backfill_lista_vacia_no_rompe():
    db = MagicMock()
    with patch.object(cr, "fetch_candles", return_value=[]):
        assert cr.backfill_symbol(db, "BTC_USD", "1D") == 0


def test_backfill_all_un_simbolo_que_falla_no_aborta_el_resto():
    db = MagicMock()

    def fake(db_, symbol, tf, **kw):
        if symbol == "MALO":
            raise RuntimeError("boom")
        return 7

    with patch.object(cr, "backfill_symbol", side_effect=fake):
        totals = cr.backfill_all(db, ["MALO", "BTC_USD"], timeframes=["1D"])

    assert totals["1D"] == 7
    db.rollback.assert_called_once()


def test_el_bucle_horario_sigue_sin_paginar():
    """El barrido periodico no debe releer historico cada hora."""
    with patch.object(cr, "http_get", return_value=_resp([_candle(1000)])) as g:
        cr.fetch_candles("BTC_USD", "1D", count=cr.RECORD_COUNT)
    assert "end_ts" not in g.call_args.kwargs["params"]
