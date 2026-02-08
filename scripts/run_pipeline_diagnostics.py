#!/usr/bin/env python3
"""
Pipeline diagnostics: DB, exchange (public ping), Telegram config.
Prints a compact PASS/FAIL report. No secrets in output.
Run from repo root:  cd backend && python3 -m scripts.run_pipeline_diagnostics
Or:                 PYTHONPATH=backend python3 scripts/run_pipeline_diagnostics.py
"""
from __future__ import annotations

import os
import sys

# Allow importing app when run from repo root
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_BACKEND = os.path.join(_REPO_ROOT, "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

os.chdir(_BACKEND)


def _main() -> int:
    report: list[str] = []
    all_pass = True

    # 1) DB connectivity
    try:
        from sqlalchemy import text
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        report.append("DB_CONNECT: PASS")
    except Exception as e:
        report.append("DB_CONNECT: FAIL (%s)" % (str(e)[:80],))
        all_pass = False

    # 2) System health (includes Telegram config, market data, signal monitor)
    try:
        from app.services.system_health import get_system_health
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            health = get_system_health(db)
            for key in ("market_data", "signal_monitor", "telegram", "trade_system"):
                comp = health.get(key, {})
                status = comp.get("status", "UNKNOWN")
                report.append(f"{key.upper()}: {status}")
                if status not in ("PASS", "WARN"):
                    all_pass = False
            # Telegram config marker (no secret)
            tg = health.get("telegram", {})
            if tg.get("bot_token_set") and tg.get("chat_id_set"):
                report.append("telegram_config_ok: true")
            else:
                report.append("telegram_config_ok: false")
        finally:
            db.close()
    except Exception as e:
        report.append("SYSTEM_HEALTH: FAIL (%s)" % (str(e)[:80],))
        all_pass = False

    # 3) Exchange connectivity (public endpoint only)
    try:
        from app.services.brokers.crypto_com_trade import trade_client

        trade_client.get_instruments()
        report.append("EXCHANGE_PING: PASS")
    except Exception as e:
        report.append("EXCHANGE_PING: FAIL (%s)" % (str(e)[:80],))
        all_pass = False

    for line in report:
        print(line)
    print("---")
    print("OVERALL:", "PASS" if all_pass else "FAIL")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(_main())
