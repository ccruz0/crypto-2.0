#!/usr/bin/env python3
"""
Reconcile stale order intents: mark intents that have no matching exchange order
as FAILED (MISSING_EXCHANGE_ORDER). Used by scripts/aws/reconcile_order_intents.sh.
Exit 0 (PASS) if no unresolved stale intents remain; exit 1 (FAIL) otherwise.
Do not print secrets or DSN.
"""
import os
import sys

# Run from backend dir (working_dir in docker is /app/backend)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    grace_minutes = int(os.environ.get("RECONCILE_GRACE_MINUTES", "5"))
    from app.database import create_db_session
    from app.services.order_intent_reconciliation import run_reconciliation

    try:
        db = create_db_session()
    except RuntimeError:
        return 1
    try:
        _marked, unresolved = run_reconciliation(db, grace_minutes=grace_minutes)
        return 0 if unresolved == 0 else 1
    except Exception:
        return 1
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
