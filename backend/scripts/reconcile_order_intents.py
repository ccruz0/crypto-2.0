#!/usr/bin/env python3
"""
CLI for order intent reconciliation. Used by scripts/aws/reconcile_order_intents.sh.
Strict semantics: exit 0 only when reconciliation ran and zero stale intents remain.
Exit 1 on DB unreachable (after retries), on exception, or when stale intents remain.
"""
import os
import sys
import logging

# Add backend to path when run as script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
debug = os.environ.get("DEBUG", "").strip() == "1"

def main() -> int:
    from sqlalchemy.exc import OperationalError
    from app.database import SessionLocal
    from app.services.order_intent_reconciliation import run_reconciliation

    if SessionLocal is None:
        print("FAIL")
        logger.error("Database not configured")
        return 1

    grace_minutes = int(os.environ.get("RECONCILE_GRACE_MINUTES", "10"))
    last_err = None
    for attempt in (1, 2):
        try:
            db = SessionLocal()
            try:
                marked, unresolved = run_reconciliation(db, grace_minutes=grace_minutes)
                if debug:
                    logger.info("marked=%s unresolved=%s", marked, unresolved)
                if unresolved > 0:
                    print("FAIL")
                    if debug:
                        logger.info("Stale intents remain: %s", unresolved)
                    return 1
                print("PASS")
                return 0
            finally:
                db.close()
        except OperationalError as e:
            last_err = e
            if debug:
                logger.info("Attempt %s: DB unreachable: %s", attempt, type(e).__name__)
            if attempt == 2:
                print("FAIL")
                logger.error("DB unreachable after retries")
                return 1
        except Exception as e:
            print("FAIL")
            logger.exception("Reconciliation failed")
            return 1
    print("FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
