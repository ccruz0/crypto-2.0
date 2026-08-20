"""Regresion: el filtro de tendencia para cortos debe exigir estructura bajista.

La comparacion era `ma50 < ema10` (alineacion ALCISTA) usada como confirmacion
de giro bajista, asi que la puerta se abria mas cuanto mas subia el mercado.
Medido sobre signal_indicator_snapshots (19-20 ago 2026): 14203 de 14810
señales SELL (95,9%) pasaban con estructura alcista.

Caso real que motivo el test: DOT_USD el 20-ago-2026 — precio 0.8257,
RSI 73.21, EMA10 0.808621, MA50 0.77369 (EMA10 un 4,4% POR ENCIMA de MA50).
Se abrio corto y cerro en stop loss a -10,01%.
"""
from app.services.trading_signals import calculate_trading_signals


def _señal(*, price, rsi, ema10, ma50, ma10w):
    return calculate_trading_signals(
        symbol="TEST_USD",
        price=price,
        rsi=rsi,
        ma50=ma50,
        ma200=ma50 * 0.99,
        ema10=ema10,
        ma10w=ma10w,
        volume=2.0,
        avg_volume=1.0,
        rsi_sell_threshold=70,
    )


def test_estructura_alcista_no_debe_disparar_corto():
    """Caso DOT 20-ago: RSI sobrecomprado pero EMA10 muy por encima de MA50."""
    r = _señal(price=0.8257, rsi=73.21, ema10=0.808621, ma50=0.77369, ma10w=0.70)
    assert r["sell_signal"] is False, (
        "Un corto no debe abrirse con EMA10 por encima de MA50 "
        "(alineacion alcista) solo porque el RSI este sobrecomprado"
    )


def test_estructura_bajista_si_confirma():
    """EMA10 por debajo de MA50 con separacion > 0.5%: giro bajista real."""
    r = _señal(price=0.79, rsi=73.0, ema10=0.75, ma50=0.80, ma10w=0.70)
    assert r["sell_signal"] is True


def test_separacion_insuficiente_no_confirma():
    """EMA10 por debajo pero con menos del 0.5% de separacion: ruido."""
    r = _señal(price=0.79, rsi=73.0, ema10=0.7990, ma50=0.8000, ma10w=0.70)
    assert r["sell_signal"] is False
