"""Regresion: volume_ratio debe ser None (NULL) cuando no hay datos, no 0.0.

Un 0.0 en la columna es indistinguible de un volumen real de cero. El bug de
mapeo de simbolos de Binance (XRP/ALGO sin sufijo _USDT -> HTTP 400) hacia que
market_updater guardara 0.0 silenciosamente, y esos ceros se leian como cifras
legitimas al comparar el dashboard contra la base de datos.
"""
from market_updater import calculate_technical_indicators


def _velas(n):
    return [{"o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 10.0} for _ in range(n)]


def test_sin_datos_devuelve_none():
    out = calculate_technical_indicators([], current_price=1.23)
    assert out["volume_ratio"] is None
    assert out["rsi"] == 50.0


def test_pocas_velas_devuelve_none():
    out = calculate_technical_indicators(_velas(10), current_price=1.0)
    assert out["volume_ratio"] is None


def test_no_devuelve_cero_enmascarado():
    out = calculate_technical_indicators([], current_price=1.0)
    assert out["volume_ratio"] != 0.0
