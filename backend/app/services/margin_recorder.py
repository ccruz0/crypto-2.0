"""Registro periodico del estado de margen.

Separado de portfolio_cache a proposito: aquel corre cada minuto y su trabajo
es servir el dashboard; este solo acumula historia y no debe poder romperlo.
Un fallo aqui no afecta a ninguna otra ruta.

NO toca ninguna ruta de trading. Solo escribe en `margin_snapshots`.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.margin_snapshot import MarginSnapshot

logger = logging.getLogger(__name__)

# Cada cuanto se toma una muestra. Cinco minutos es un compromiso: el margen
# se mueve con el precio, asi que muestrear cada minuto multiplica filas sin
# añadir señal, y cada hora se perderia justamente el pico de un crash — que
# es el unico momento que esta tabla existe para capturar.
RECORD_INTERVAL_SECONDS = int(os.getenv("MARGIN_RECORD_INTERVAL_SECONDS", "300"))


def _borrowed_usd(db: Session) -> Optional[float]:
    """Deuda viva agregada, o None si no se puede leer.

    Devolver None y no 0.0 es deliberado: un cero significa "no debo nada" y
    aqui hace falta poder distinguirlo de "no lo pude leer".
    """
    try:
        from app.models.portfolio_loan import PortfolioLoan

        total = (
            db.query(func.sum(PortfolioLoan.borrowed_usd_value))
            .filter(PortfolioLoan.is_active == True)  # noqa: E712
            .scalar()
        )
        return float(total or 0.0)
    except Exception as exc:
        logger.warning("[MARGIN] no se pudo leer la deuda viva: %s", exc)
        return None


def record_margin_snapshot(db: Session) -> Optional[MarginSnapshot]:
    """Toma una muestra. Devuelve la fila escrita, o None si no se pudo."""
    try:
        from app.services.brokers.crypto_com_trade import trade_client

        equity, exposure, _daily_pct = trade_client.get_equity_from_user_balance()
    except Exception as exc:
        # El exchange puede estar caido o las credenciales ausentes; no se
        # escribe una fila con ceros, que seria indistinguible de una cuenta
        # vacia de verdad.
        logger.warning("[MARGIN] no se pudo leer el equity: %s", exc)
        return None

    equity_f = float(equity or 0.0)
    exposure_f = float(exposure or 0.0)

    free_margin = equity_f - exposure_f
    # Sin equity no hay ratio posible. NULL, no 0.
    margin_ratio = (exposure_f / equity_f) if equity_f > 0 else None

    row = MarginSnapshot(
        equity=equity_f,
        exposure=exposure_f,
        borrowed_usd=_borrowed_usd(db),
        free_margin=free_margin,
        margin_ratio=margin_ratio,
    )
    db.add(row)
    db.commit()

    logger.info(
        "[MARGIN] equity=%.2f exposure=%.2f libre=%.2f ratio=%s",
        equity_f, exposure_f, free_margin,
        f"{margin_ratio:.4f}" if margin_ratio is not None else "n/d",
    )
    return row


def _run_margin_sample() -> None:
    """One margin sample — sync; run via background executor, not on the event loop."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        record_margin_snapshot(db)
    finally:
        db.close()


async def start_margin_recorder_loop() -> None:
    """Muestrea cada RECORD_INTERVAL_SECONDS. Nunca muere por una excepcion."""
    import asyncio

    from app.utils.background_executor import overlap_guard, run_in_background

    logger.info(
        "[MARGIN] bucle de registro iniciado (cada %ds)", RECORD_INTERVAL_SECONDS
    )
    while True:
        try:
            async with overlap_guard("margin_sample") as acquired:
                if acquired:
                    await run_in_background(_run_margin_sample)
        except asyncio.CancelledError:  # pragma: no cover
            logger.info("[MARGIN] bucle cancelado")
            raise
        except Exception as exc:  # pragma: no cover - el bucle debe sobrevivir
            logger.error("[MARGIN] iteracion fallida: %s", exc, exc_info=True)
        await asyncio.sleep(RECORD_INTERVAL_SECONDS)
