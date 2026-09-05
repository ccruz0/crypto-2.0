"""El vigilante de exposicion ciega no puede morir en silencio.

Un vigilante que lanza una excepcion deja las gauges con el ultimo valor bueno,
y eso se lee igual que "no hay exposicion" -- que es exactamente el fallo que
este modulo existe para impedir. Estos tests fijan ese contrato.
"""

import pytest

from app.services.blind_exposure_monitor import (
    _bases_from_symbols,
    _dust_usd,
    collect_blind_exposure,
    refresh_blind_exposure_metrics,
)


class _BrokenSession:
    """Todo lo que se le pida revienta."""

    def query(self, *args, **kwargs):
        raise RuntimeError("db caida")


def test_dust_floor_matches_trade_guards_default():
    # Mismo suelo que usan las guardas de trading; si alguien cambia uno sin el
    # otro, el vigilante contaria polvo que la politica excluye a proposito.
    assert _dust_usd() == 5.0


def test_collect_never_raises_when_db_is_broken():
    stats = collect_blind_exposure(_BrokenSession())
    assert stats["total_usd"] == 0.0
    assert stats["symbols_total"] == 0
    # Y el fallo queda contado, no escondido: es lo que dispara
    # BlindExposureWatchdogBlind.
    assert stats["errors"] >= 1


def test_refresh_never_raises_and_returns_stats():
    stats = refresh_blind_exposure_metrics(_BrokenSession())
    assert set(
        ["total_usd", "symbols_total", "max_symbol_usd", "errors", "details"]
    ).issubset(stats.keys())


def test_stats_shape_is_stable():
    stats = collect_blind_exposure(_BrokenSession())
    assert isinstance(stats["details"], list)
    assert isinstance(stats["max_symbol"], str)


def test_sibling_pairs_collapse_to_one_base():
    """BTC_USD y BTC_USDT son el mismo lote, no dos.

    count_open_lots_for_symbol reconstruye lotes del BASE, asi que recorrer la
    watchlist par a par valoraba dos veces el mismo dinero e inflaba la gauge
    hasta disparar las alertas sobre un libro que las guardas tratan como una
    sola moneda. Lo cazo Cursor Bugbot en la PR #666.
    """
    bases = _bases_from_symbols(
        ["BTC_USD", "BTC_USDT", "ETH_USD", "ETH_USDT", "DOGE_USD"]
    )
    assert sorted(bases.keys()) == ["BTC", "DOGE", "ETH"]
    assert bases["BTC"] == ["BTC_USD", "BTC_USDT"]
    assert bases["DOGE"] == ["DOGE_USD"]


def test_bases_are_normalised_and_deduped():
    bases = _bases_from_symbols(["btc_usd", "BTC_USD", "  ", "", "XRP"])
    # Mismo par en minusculas no crea una base nueva ni se repite en la lista.
    assert bases["BTC"] == ["BTC_USD"]
    # Un simbolo sin guion bajo es su propia base.
    assert bases["XRP"] == ["XRP"]
    assert "" not in bases
