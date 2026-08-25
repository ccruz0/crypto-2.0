"""Ingesta de velas historicas desde Crypto.com.

Idempotente por diseno: la unicidad (symbol, timeframe, open_time) la impone
la BD, asi que reejecutar el job no duplica. Solo inserta lo que falta.

NO toca ninguna ruta de trading. Solo escribe en `candles`.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, Iterable, List, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.candle import Candle
from app.utils.http_client import http_get

logger = logging.getLogger(__name__)

CANDLE_URL = "https://api.crypto.com/exchange/v1/public/get-candlestick"

# La API devuelve como maximo ~300 velas por peticion.
MAX_COUNT = 300

TIMEFRAMES = ("1h", "4h", "1D")


def fetch_candles(
    symbol: str,
    timeframe: str,
    count: int = MAX_COUNT,
    *,
    timeout: float = 15.0,
) -> List[Dict]:
    """Devuelve velas normalizadas, o [] si falla.

    Devolver [] y no None es deliberado: el llamador itera sin comprobar, y un
    fallo de red no debe distinguirse de "no hay datos" para el bucle. El error
    se registra aqui.
    """
    try:
        response = http_get(
            CANDLE_URL,
            params={
                "instrument_name": symbol,
                "timeframe": timeframe,
                "count": count,
            },
            timeout=timeout,
            calling_module="candle_recorder",
        )
        if response.status_code != 200:
            logger.warning(
                "[CANDLES] HTTP %s para %s %s",
                response.status_code, symbol, timeframe,
            )
            return []
        payload = response.json()
        rows = (payload.get("result") or {}).get("data") or []
    except Exception as exc:
        logger.warning("[CANDLES] fallo al pedir %s %s: %s", symbol, timeframe, exc)
        return []

    out: List[Dict] = []
    for row in rows:
        try:
            candle = {
                "open_time": int(row["t"]),
                "open": float(row["o"]),
                "high": float(row["h"]),
                "low": float(row["l"]),
                "close": float(row["c"]),
                "volume": float(row.get("v") or 0.0),
            }
        except (KeyError, TypeError, ValueError):
            # Una vela malformada no invalida el resto del lote.
            continue
        # Una vela con precios a cero no es un dato real: es un hueco del
        # exchange. Descartarla aqui evita que un backtest la lea como una
        # caida del 100%.
        if candle["close"] <= 0 or candle["high"] <= 0 or candle["low"] <= 0:
            continue
        out.append(candle)

    out.sort(key=lambda c: c["open_time"])
    return out


def store_candles(
    db: Session,
    symbol: str,
    timeframe: str,
    candles: Iterable[Dict],
    *,
    source: str = "crypto_com",
) -> int:
    """Inserta las velas que falten. Devuelve cuantas se insertaron."""
    rows = [
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "exchange": "CRYPTO_COM",
            "open_time": c["open_time"],
            "open": c["open"],
            "high": c["high"],
            "low": c["low"],
            "close": c["close"],
            "volume": c.get("volume"),
            "source": source,
        }
        for c in candles
    ]
    if not rows:
        return 0

    # ON CONFLICT DO NOTHING: la vela mas reciente puede estar aun abierta y
    # cambiar. Se prefiere conservar la primera version registrada antes que
    # reescribir historico ya leido por un backtest.
    stmt = (
        pg_insert(Candle.__table__)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_candles_symbol_tf_time")
    )
    result = db.execute(stmt)
    db.commit()
    return int(result.rowcount or 0)


def record_symbol(
    db: Session,
    symbol: str,
    timeframe: str,
    *,
    count: int = MAX_COUNT,
) -> int:
    candles = fetch_candles(symbol, timeframe, count=count)
    if not candles:
        return 0
    return store_candles(db, symbol, timeframe, candles)


def record_all(
    db: Session,
    symbols: List[str],
    timeframes: Iterable[str] = TIMEFRAMES,
) -> Dict[str, int]:
    """Recorre simbolos x timeframes. Devuelve {timeframe: filas_nuevas}."""
    totals: Dict[str, int] = {}
    for tf in timeframes:
        inserted = 0
        for symbol in symbols:
            try:
                inserted += record_symbol(db, symbol, tf)
            except Exception as exc:
                # Un simbolo que falla no debe abortar el barrido completo.
                logger.warning("[CANDLES] %s %s fallo: %s", symbol, tf, exc)
                db.rollback()
        totals[tf] = inserted
        logger.info("[CANDLES] %s: %d velas nuevas", tf, inserted)
    return totals

# --- Bucle de ingesta periodica ---------------------------------------------

# Cada cuanto se ejecuta el barrido completo. Una hora es el minimo util: el
# timeframe mas corto que se registra es 1h, asi que barrer mas a menudo solo
# reescribiria la misma vela abierta.
RECORD_INTERVAL_SECONDS = int(os.getenv("CANDLE_RECORD_INTERVAL_SECONDS", "3600"))

# Cuantas velas se piden en cada barrido. 300 es el maximo de la API y sirve
# tambien como relleno: si el job estuvo caido un dia, el siguiente barrido
# recupera el hueco sin intervencion.
RECORD_COUNT = int(os.getenv("CANDLE_RECORD_COUNT", "300"))


def _symbols_from_watchlist(db: Session) -> List[str]:
    """Simbolos a registrar: los de la watchlist.

    Si la watchlist esta vacia devuelve [] y el barrido no hace nada — es
    preferible no registrar a inventar una lista fija que se desincronice de
    lo que el bot realmente opera.
    """
    try:
        from app.models.watchlist import WatchlistItem

        rows = db.query(WatchlistItem.symbol).distinct().all()
        return sorted({r[0] for r in rows if r and r[0]})
    except Exception as exc:
        logger.warning("[CANDLES] no se pudo leer la watchlist: %s", exc)
        return []


async def start_candle_recorder_loop() -> None:
    """Registra velas cada RECORD_INTERVAL_SECONDS. Nunca muere por una excepcion."""
    import asyncio

    from app.database import SessionLocal

    logger.info(
        "[CANDLES] bucle de registro iniciado (cada %ds, %d velas, timeframes=%s)",
        RECORD_INTERVAL_SECONDS, RECORD_COUNT, ",".join(TIMEFRAMES),
    )
    while True:
        try:
            db = SessionLocal()
            try:
                symbols = _symbols_from_watchlist(db)
                if not symbols:
                    logger.info("[CANDLES] watchlist vacia, no hay nada que registrar")
                else:
                    totals = record_all(db, symbols)
                    logger.info(
                        "[CANDLES] barrido completo: %d simbolos, nuevas=%s",
                        len(symbols),
                        totals,
                    )
            finally:
                db.close()
        except asyncio.CancelledError:  # pragma: no cover
            logger.info("[CANDLES] bucle cancelado")
            raise
        except Exception as exc:  # pragma: no cover - el bucle debe sobrevivir
            logger.error("[CANDLES] iteracion fallida: %s", exc, exc_info=True)
        await asyncio.sleep(RECORD_INTERVAL_SECONDS)
