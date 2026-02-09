#!/usr/bin/env python3
"""
Week 5 health snapshot: last N decisions by symbol, dedup_events count, circuit breaker state.
Lightweight; no heavy dependencies. Run from repo root:
  cd /Users/carloscruz/automated-trading-platform
  PYTHONPATH=backend python3 scripts/run_week5_health_snapshot.py
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_BACKEND = os.path.join(_REPO_ROOT, "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.chdir(_BACKEND)


def _main() -> int:
    report: list[str] = []
    report.append("WEEK5_HEALTH_SNAPSHOT")
    report.append("---")

    # 1) Last N decisions by symbol (from watchlist_signal_state if available)
    try:
        from app.database import SessionLocal
        from app.models.watchlist_signal_state import WatchlistSignalState
        db = SessionLocal()
        try:
            rows = (
                db.query(WatchlistSignalState)
                .order_by(WatchlistSignalState.evaluated_at_utc.desc().nullslast())
                .limit(20)
                .all()
            )
            report.append("last_decisions_count: %s" % len(rows))
            for r in rows[:10]:
                sym = getattr(r, "symbol", "?")
                side = getattr(r, "signal_side", "?")
                at = getattr(r, "evaluated_at_utc", None)
                report.append("  symbol=%s side=%s evaluated_at=%s" % (sym, side, at))
        finally:
            db.close()
    except Exception as e:
        report.append("last_decisions: FAIL (%s)" % (str(e)[:80],))

    # 2) Dedup events count (recent)
    try:
        from app.database import SessionLocal
        from app.services.dedup_events_week5 import count_dedup_events_recent
        db = SessionLocal()
        try:
            n = count_dedup_events_recent(db, minutes=60)
            report.append("dedup_events_last_60min: %s" % n)
        finally:
            db.close()
    except Exception as e:
        report.append("dedup_events_last_60min: FAIL (%s)" % (str(e)[:80],))

    # 3) Circuit breaker state
    try:
        from app.core.retry_circuit_week5 import get_exchange_circuit, get_telegram_circuit
        ex = get_exchange_circuit()
        tg = get_telegram_circuit()
        report.append("circuit_exchange: %s" % ex.state())
        report.append("circuit_telegram: %s" % tg.state())
    except Exception as e:
        report.append("circuit_breaker: FAIL (%s)" % (str(e)[:80],))

    report.append("---")
    for line in report:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
