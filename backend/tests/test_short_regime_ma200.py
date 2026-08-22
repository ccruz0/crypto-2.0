"""Regime filter de cortos: price < MA200 obligatorio, fail-closed.

Decision de Carlos 2026-08-22 tras el barrido del 21-22 ago (11 stops, -177 USD):
un corto no puede abrirse con el precio por encima de su MA200.
"""
import os

os.environ.setdefault("SYSTEM_CORE_GUARDS_ENABLED", "true")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.services.system_core_trade_guards as g


def _db():
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE market_data (symbol TEXT, ma200 REAL)"))
        c.execute(text("INSERT INTO market_data VALUES ('BTC_USD', 60000.0)"))
    return sessionmaker(bind=eng)()


def test_corto_por_encima_de_ma200_bloqueado():
    blocked, reason = g._short_regime_block(_db(), "BTC_USD", "BTC", 70000.0)
    assert blocked
    assert "price_above_ma200" in reason


def test_corto_por_debajo_de_ma200_permitido():
    blocked, reason = g._short_regime_block(_db(), "BTC_USD", "BTC", 50000.0)
    assert not blocked


def test_sin_ma200_bloqueado_fail_closed():
    blocked, reason = g._short_regime_block(_db(), "XXX_USD", "XXX", 1.0)
    assert blocked
    assert "ma200_unavailable" in reason


def test_precio_invalido_bloqueado():
    blocked, reason = g._short_regime_block(_db(), "BTC_USD", "BTC", 0.0)
    assert blocked
    assert "price_unavailable" in reason


def test_gate_completo_bloquea_corto_en_alcista(monkeypatch):
    monkeypatch.setattr(g, "_GUARDS_ON", True)
    monkeypatch.setattr(g, "_SHORT_REGIME_ON", True)
    allowed, reason = g.check_system_core_short_entry_allowed(
        _db(), "BTC_USD", 100.0, price=70000.0
    )
    assert not allowed
    assert "short_regime" in reason


def test_kill_switch_desactiva_el_filtro(monkeypatch):
    monkeypatch.setattr(g, "_GUARDS_ON", True)
    monkeypatch.setattr(g, "_SHORT_REGIME_ON", False)
    monkeypatch.setattr(g, "_daily_drawdown_violation", lambda db: (False, ""))
    monkeypatch.setattr(g, "count_distinct_symbols_with_open_positions", lambda db: 0)
    from app.services import order_position_service

    monkeypatch.setattr(
        order_position_service, "count_open_positions_for_symbol", lambda db, b, **k: 0
    )
    allowed, reason = g.check_system_core_short_entry_allowed(
        _db(), "BTC_USD", 100.0, price=70000.0
    )
    assert allowed, reason
