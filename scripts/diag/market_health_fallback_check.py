#!/usr/bin/env python3
"""
Prove market_data fallback logic without touching prod.
Runs the fallback query directly: count distinct symbols in market_prices
with updated_at within threshold, and oldest updated_at.
Use from backend container: docker exec backend-aws python /app/scripts/diag/market_health_fallback_check.py
Or with DATABASE_URL set: python scripts/diag/market_health_fallback_check.py
"""
import os
import sys

def main():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 1
    threshold_minutes = float(os.getenv("HEALTH_STALE_MARKET_MINUTES", "30"))
    pass_min = int(os.getenv("MARKET_HEALTH_PASS_MIN_SYMBOLS", "5"))

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        print("sqlalchemy not installed", file=sys.stderr)
        return 1

    engine = create_engine(url, connect_args={"connect_timeout": 5})
    with engine.connect() as conn:
        # Distinct symbols with updated_at >= now() - threshold
        r = conn.execute(
            text("""
                SELECT COUNT(DISTINCT symbol) AS cnt,
                       EXTRACT(EPOCH FROM (NOW() - MIN(updated_at)))/60.0 AS max_age_minutes
                FROM market_prices
                WHERE symbol IS NOT NULL
                  AND updated_at IS NOT NULL
                  AND updated_at >= NOW() - :threshold * INTERVAL '1 minute'
            """),
            {"threshold": threshold_minutes},
        )
        row = r.fetchone()
        distinct_recent_symbols = row[0] if row else 0
        max_age_minutes = round(float(row[1] or 0), 2) if row and row[1] is not None else None

        if distinct_recent_symbols >= pass_min:
            status = "PASS"
        elif distinct_recent_symbols >= 1:
            status = "WARN"
        else:
            status = "FAIL"

    print("distinct_recent_symbols:", distinct_recent_symbols)
    print("max_age_minutes:", max_age_minutes)
    print("computed status:", status)
    return 0 if status != "FAIL" else 1

if __name__ == "__main__":
    sys.exit(main())
