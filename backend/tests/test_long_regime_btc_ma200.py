"""Filtro de regimen BTC>MA200 para compras (espejo del filtro de cortos).

Medicion que lo motiva (23-ago-2026, 4 anos, 13 alts): retorno medio diario
de las alts ~0% con BTC sobre su MA200 diaria frente a ~-22% anualizado con
BTC por debajo. El filtro vive en la puerta comun de compra
(check_system_core_buy_allowed) para cortar cualquier ruta de entrada,
incluida la ruta Auto.
"""
from unittest.mock import MagicMock

import app.services.system_core_trade_guards as guards


def _db(row):
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = row
    return db


def test_blocks_when_btc_below_ma200():
    blocked, reason = guards._long_btc_regime_block(_db((60000.0, 68000.0)))
    assert blocked is True
    assert "btc_below_ma200" in reason


def test_allows_when_btc_above_ma200():
    blocked, reason = guards._long_btc_regime_block(_db((77000.0, 68000.0)))
    assert blocked is False
    assert reason == ""


def test_fail_closed_without_btc_row():
    blocked, reason = guards._long_btc_regime_block(_db(None))
    assert blocked is True
    assert "unavailable" in reason


def test_fail_closed_on_db_error():
    db = MagicMock()
    db.execute.side_effect = RuntimeError("db down")
    blocked, _ = guards._long_btc_regime_block(db)
    assert blocked is True


def test_buy_gate_blocks_via_btc_regime(monkeypatch):
    monkeypatch.setattr(guards, "_GUARDS_ON", True)
    monkeypatch.setattr(guards, "_LONG_BTC_REGIME_ON", True)
    ok, reason = guards.check_system_core_buy_allowed(
        _db((60000.0, 68000.0)), "APT_USD", 100.0, rsi=None, ma200=None, price=1.0
    )
    assert ok is False
    assert "long_btc_regime" in reason


def test_kill_switch_skips_regime(monkeypatch):
    monkeypatch.setattr(guards, "_GUARDS_ON", True)
    monkeypatch.setattr(guards, "_LONG_BTC_REGIME_ON", False)
    monkeypatch.setattr(guards, "_daily_drawdown_violation", lambda db: (False, ""))
    calls = []
    monkeypatch.setattr(
        guards, "_long_btc_regime_block", lambda db: calls.append(1) or (True, "x")
    )
    guards.check_system_core_buy_allowed(
        _db(None), "APT_USD", 1.0, rsi=None, ma200=None, price=1.0
    )
    assert calls == []
