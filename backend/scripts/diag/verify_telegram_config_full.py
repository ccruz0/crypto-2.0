#!/usr/bin/env python3
"""
Verify Telegram config: tg_enabled_aws, env vars (masked), RUN_TELEGRAM.

Run inside backend container:
  docker compose --profile aws exec backend-aws python scripts/diag/verify_telegram_config_full.py
"""
import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(backend_dir))


def mask(s: str) -> str:
    if not s or len(s) < 8:
        return "***" if s else "(empty)"
    return s[:4] + "..." + s[-2:] + f" ({len(s)} chars)"


def main():
    print("=== tg_enabled_aws (DB) ===")
    try:
        from app.database import create_db_session
        from app.models.trading_settings import TradingSettings

        db = create_db_session()
        for env in ("aws", "local"):
            key = f"tg_enabled_{env}"
            s = db.query(TradingSettings).filter(TradingSettings.setting_key == key).first()
            val = s.setting_value if s else "(not set)"
            default = "true" if env == "local" else "false"
            allows = (val if s else default).lower() == "true"
            status = "ALLOWS" if allows else "BLOCKS"
            print(f"  {key}: {val} -> {status}")
        db.close()
    except Exception as e:
        print(f"  Error: {e}")

    print("\n=== Env vars (masked) ===")
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_AUTH_USER_ID", "RUN_TELEGRAM", "RUN_TELEGRAM_POLLER"):
        v = os.getenv(k, "")
        print(f"  {k}: {mask(v) if v else '(not set)'}")

    print("\nDone.")


if __name__ == "__main__":
    main()
