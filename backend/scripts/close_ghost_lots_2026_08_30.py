#!/usr/bin/env python3
"""Cierra en LIBROS entradas fantasma del BOT insertando stubs STUB-CLOSED-*.

Auditoria 28/30-ago-2026 (registro en
docs/project-history/position-count-shadow-exit-criteria.md):

  5755600492526823562  APT_USD SELL 17.65 (02-ago) protecciones CANCELLED/REJECTED 11-ago
  5755600492576389211  APT_USD SELL 17.54 (03-ago) protecciones CANCELLED 11-ago

Sin cierre FILLED vinculado y sin inventario real en wallet (verificado contra
la sombra: el corto neto de APT era solo la posicion viva). El FIFO los
mantiene abiertos para siempre y el HOURLY SL/TP AUDIT los reclama cada hora.

DESCARTADO del lote — 5755600480707749502 (BTC_USD SELL 0.01112):
el dry-run del 30-ago lo revelo. exchange_create_time = 2026-01-05, no junio
(la fecha de junio era created_at: cuando lo IMPORTAMOS, no cuando se opero).
order_type LIMIT, trade_signal_id NULL, ~1.030 USD frente a los ~100 USD de
toda entrada automatica: es una operacion MANUAL importada en el backfill de
junio junto a otras 345 de BTC. Y el wallet BTC (-0.00132) ya queda explicado
por el corto del 29-ago sin necesidad de el. Inventarle un cierre a 92.688
contaminaria el historico con un P&L falso. Su limpieza es otra conversacion.

De ahi la guarda require_bot_origin: sin trade_signal_id NI intent, la fila no
es del bot y este script no la toca. Habria descartado el BTC sola.

MECANISMO — el precedente del 25-jul-2026, verificado empiricamente el 30-ago:
28 stubs / 14 padres, DOS patas (SL+TP) por padre, side OPUESTO al padre,
qty = la del padre, precio = el de entrada (P&L 0). CERO de aquellos padres
sigue en rebuild_open_lots hoy: el stub asienta el lot. Ademas silencia el
audit por _is_naked -> get_filled_protection_order (sl_tp_protection.py:284,
sin exclusion de stubs; docstring :302 "or stubbed closed" — es la puerta
disenada para esto). trade_outcome_builder EXCLUYE los stubs (leccion de
julio, :190,:739), asi que no se fabrican outcomes con P&L 0.

NO toca el exchange. Solo INSERT en exchange_orders, y solo con --live.
Por defecto, dry-run: imprime el plan y verifica las firmas.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.utils.ops_stub_orders import is_ops_stub_closed_order_id

TARGET_IDS = [
    "5755600492526823562",
    "5755600492576389211",
]

TERMINAL = {"CANCELLED", "REJECTED", "EXPIRED", "FAILED"}
MIN_AGE_DAYS = 14


def _status(x) -> str:
    return str(getattr(x, "value", x) or "").upper()


def has_bot_origin(db, e: ExchangeOrder) -> bool:
    """True si la entrada la coloco el bot (trade_signal_id o order_intent)."""
    if getattr(e, "trade_signal_id", None):
        return True
    row = db.execute(
        text("SELECT 1 FROM order_intents WHERE order_id = :oid LIMIT 1"),
        {"oid": str(e.exchange_order_id)},
    ).first()
    return row is not None


def verify_target(db, entry_id: str, *, require_bot_origin: bool = True):
    """Devuelve (entry, motivo_de_rechazo|None)."""
    e = db.query(ExchangeOrder).filter(
        ExchangeOrder.exchange_order_id == entry_id
    ).first()
    if e is None:
        return None, "no existe en exchange_orders"
    if _status(e.status) != "FILLED":
        return e, f"status={_status(e.status)}, no FILLED"
    if _status(e.side) != "SELL":
        return e, f"side={_status(e.side)}: este script solo cubre cortos"
    if (e.order_role or "").upper() in {"STOP_LOSS", "TAKE_PROFIT", "FLATTEN"}:
        return e, f"order_role={e.order_role}: no es una entrada"
    if require_bot_origin and not has_bot_origin(db, e):
        return e, ("sin trade_signal_id ni order_intent: no es entrada del bot "
                   "(posible operacion manual importada) — fuera de alcance")
    # exchange_create_time, NO created_at: created_at es cuando la fila entro en
    # NUESTRA base (un backfill puede importar operaciones de meses atras).
    ref = e.exchange_create_time
    if ref is not None and ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    if ref is None:
        return e, "sin exchange_create_time: no se puede datar la operacion"
    if ref > datetime.now(timezone.utc) - timedelta(days=MIN_AGE_DAYS):
        return e, f"demasiado reciente (< {MIN_AGE_DAYS} dias): no es firma de fantasma"
    children = db.query(ExchangeOrder).filter(
        ExchangeOrder.parent_order_id == entry_id
    ).all()
    if not children:
        return e, "sin hijos: no hubo intento de proteccion — revisar a mano"
    for c in children:
        if is_ops_stub_closed_order_id(str(c.exchange_order_id or "")):
            return e, f"ya tiene stub {c.exchange_order_id}: nada que hacer"
        cs = _status(c.status)
        if cs == "FILLED":
            return e, f"tiene hijo FILLED {c.exchange_order_id}: NO es fantasma"
        if cs not in TERMINAL:
            return e, f"hijo {c.exchange_order_id} en estado no terminal {cs}"
    return e, None


def build_stubs(e: ExchangeOrder):
    """Dos patas, convencion del 25-jul: side opuesto, qty y precio del padre."""
    qty = e.cumulative_quantity or e.quantity
    price = e.avg_price or e.price
    now = datetime.now(timezone.utc)
    out = []
    for role in ("STOP_LOSS", "TAKE_PROFIT"):
        out.append(ExchangeOrder(
            exchange_order_id=f"STUB-CLOSED-{role}-{e.exchange_order_id}",
            symbol=e.symbol,
            side=OrderSideEnum.BUY,   # cierre de corto
            order_type="STOP_LIMIT" if role == "STOP_LOSS" else "TAKE_PROFIT_LIMIT",
            status=OrderStatusEnum.FILLED,
            price=price,
            avg_price=price,
            quantity=qty,
            cumulative_quantity=qty,
            cumulative_value=(Decimal(str(price)) * Decimal(str(qty))) if price and qty else None,
            order_role=role,
            parent_order_id=e.exchange_order_id,
            exchange_create_time=now,
            exchange_update_time=now,
            created_at=now,
        ))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="insertar de verdad; sin esto, dry-run")
    args = parser.parse_args()

    db = SessionLocal()
    planned = []
    try:
        for tid in TARGET_IDS:
            e, reason = verify_target(db, tid)
            if reason:
                print(f"SKIP  {tid}: {reason}")
                continue
            stubs = build_stubs(e)
            qty = e.cumulative_quantity or e.quantity
            print(f"PLAN  {tid} {e.symbol} SELL qty={qty} "
                  f"operada={e.exchange_create_time} "
                  f"-> insertar {len(stubs)} stubs BUY (SL+TP) a precio de entrada")
            for s in stubs:
                print(f"        {s.exchange_order_id}")
            planned.extend(stubs)

        if not planned:
            print("Nada que insertar.")
            return 0
        if not args.live:
            print(f"\nDRY-RUN: {len(planned)} filas NO insertadas. "
                  f"Ejecuta con --live para aplicar.")
            return 0

        for s in planned:
            db.add(s)
        db.commit()
        print(f"\nLIVE: {len(planned)} stubs insertados.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
