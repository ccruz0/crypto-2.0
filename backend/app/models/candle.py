"""Historical OHLCV candles.

Existe porque `market_data` guarda UNA fila por simbolo (indice UNIQUE sobre
`symbol`): es la foto del estado actual, no una serie temporal. Sin serie no
se puede backtestear nada sin volver a descargar de la API publica, que solo
da 300 velas y siempre del mismo tramo reciente.

Ver `atp-backtest-lado-corto-veredicto` (25-ago-2026): toda la serie de
backtests de ese dia choco contra ventanas de 13-50 dias de un unico regimen
alcista y muestras de 20-100 casos.
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, BigInteger, Index, UniqueConstraint
from sqlalchemy.sql import func
from app.database import Base


class Candle(Base):
    """Una vela OHLCV para (symbol, timeframe, open_time)."""

    __tablename__ = "candles"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, index=True)  # 1h, 4h, 1D
    exchange = Column(String(50), default="CRYPTO_COM")

    # open_time en epoch ms: es la clave natural que da el exchange y evita
    # ambiguedades de zona horaria al deduplicar.
    open_time = Column(BigInteger, nullable=False, index=True)

    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=True)

    source = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # La deduplicacion es responsabilidad de la BD, no del ingestor: si el
        # job se solapa consigo mismo o se reintenta, no duplica filas.
        UniqueConstraint("symbol", "timeframe", "open_time", name="uq_candles_symbol_tf_time"),
        # El backtest siempre lee "una serie ordenada de un simbolo": este
        # indice compuesto es el que sirve esa consulta.
        Index("ix_candles_symbol_tf_time", "symbol", "timeframe", "open_time"),
    )

    def __repr__(self):
        return (
            f"<Candle({self.symbol} {self.timeframe} "
            f"t={self.open_time} c={self.close})>"
        )
