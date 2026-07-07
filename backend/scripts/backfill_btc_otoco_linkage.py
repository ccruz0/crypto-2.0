"""
Backfill the real OTOCO parent->child linkage for BTC take-profit orders.

Context
-------
On this account each BUY was placed on Crypto.com as an OTOCO with its own
attached TP order. The correct buy<->TP pairing is therefore the exchange
parent->child relationship, NOT FIFO time order. Historically the
``exchange_orders`` rows were backfilled/reconciled WITHOUT the linkage columns
populated (``parent_order_id`` / ``order_role`` were NULL on these rows), so the
Expected-TP engine fell back to FIFO and produced wrong pairings.

The authoritative mapping below was established from real order data and
cross-checked three independent ways (all agree, and all match the operator's
Crypto.com app order history):

  * client_oid adjacency  : TP.order_id == BUY.client_oid + 1
                            (78,000<-71,100 ; 71,000<-63,244.37 ; 67,000<-59,100)
  * co-creation timestamp : OTOCO parent+child created within milliseconds
                            (also confirms 65,000<-60,500)
  * quantity elimination  : 82,000 (0.29925 = 0.30 post-fee, a separately placed
                            plain LIMIT) pairs to the remaining 75,100 BUY

Verified pairing (TP price -> parent BUY price):
    67,000 -> 59,100   (COVERS the 1.30 lot)
    65,000 -> 60,500
    71,000 -> 63,244.37
    78,000 -> 71,100
    82,000 -> 75,100

This script is idempotent: it only writes when a value differs, and re-running is
a no-op. It performs NO exchange calls and creates NO SL/TP orders. It only
reconciles local DB linkage columns so the engine can join deterministically.
"""
import sys

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder

# TP exchange_order_id -> (parent BUY exchange_order_id, human note)
LINKAGE = {
    "73817490101952837": ("5755600491091887888", "TP 67,000 -> BUY 1.30 @ 59,100"),
    "73817490101945043": ("5755600489811716124", "TP 65,000 -> BUY 0.30 @ 60,500"),
    "73817490101944530": ("5755600489717738162", "TP 71,000 -> BUY 0.30 @ 63,244.37"),
    "73817490101936697": ("5755600489289088548", "TP 78,000 -> BUY 0.30 @ 71,100"),
    "5755600489253467765": ("5755600488945374736", "TP 82,000 -> BUY 0.30 @ 75,100"),
}


def main(apply: bool = True) -> int:
    db = SessionLocal()
    changed = 0
    try:
        for tp_id, (buy_id, note) in LINKAGE.items():
            tp = db.query(ExchangeOrder).filter(
                ExchangeOrder.exchange_order_id == tp_id
            ).one_or_none()
            if tp is None:
                print(f"[skip] TP {tp_id} not found in DB ({note})")
                continue

            buy = db.query(ExchangeOrder).filter(
                ExchangeOrder.exchange_order_id == buy_id
            ).one_or_none()
            if buy is None:
                print(f"[skip] parent BUY {buy_id} not found in DB ({note})")
                continue

            needs = []
            if (tp.parent_order_id or "") != buy_id:
                needs.append(f"parent_order_id {tp.parent_order_id!r} -> {buy_id!r}")
            if (tp.order_role or "") != "TAKE_PROFIT":
                needs.append(f"order_role {tp.order_role!r} -> 'TAKE_PROFIT'")

            if not needs:
                print(f"[ok]   {note} (already linked)")
                continue

            print(f"[set]  {note}: " + "; ".join(needs))
            if apply:
                tp.parent_order_id = buy_id
                tp.order_role = "TAKE_PROFIT"
                changed += 1

        if apply and changed:
            db.commit()
            print(f"\nCommitted {changed} linkage update(s).")
        elif apply:
            print("\nNo changes needed (idempotent no-op).")
        else:
            print("\nDry-run only; no changes written.")
        return 0
    except Exception as exc:  # pragma: no cover - operational script
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    sys.exit(main(apply=not dry))
