"""El vigilante de exposicion ciega no puede morir en silencio.

Un vigilante que lanza una excepcion deja las gauges con el ultimo valor bueno,
y eso se lee igual que "no hay exposicion" -- que es exactamente el fallo que
este modulo existe para impedir. Estos tests fijan ese contrato.
"""

import pytest

from app.services.blind_exposure_monitor import (
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
