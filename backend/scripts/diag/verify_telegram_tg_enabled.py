#!/usr/bin/env python3
"""
Verify and optionally update tg_enabled_aws in TradingSettings.

tg_enabled_aws = "true"  → Telegram messages ALLOWED on AWS
tg_enabled_aws = "false" or missing → Telegram messages BLOCKED on AWS

Usage:
  # Verify only (no changes)
  python scripts/diag/verify_telegram_tg_enabled.py

  # Verify and set to true (enable Telegram on AWS)
  python scripts/diag/verify_telegram_tg_enabled.py --set-true

  # Run inside backend container on EC2
  docker compose --profile aws exec backend-aws python scripts/diag/verify_telegram_tg_enabled.py --set-true
"""
import argparse
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(backend_dir))

from app.database import create_db_session
from app.models.trading_settings import TradingSettings


def main():
    parser = argparse.ArgumentParser(description="Verify/update tg_enabled_aws in TradingSettings")
    parser.add_argument("--set-true", action="store_true", help="Set tg_enabled_aws to 'true' if missing or false")
    args = parser.parse_args()

    try:
        db = create_db_session()
    except RuntimeError as e:
        print(f"❌ Database not available: {e}")
        sys.exit(1)
    try:
        for env in ("aws", "local"):
            key = f"tg_enabled_{env}"
            setting = db.query(TradingSettings).filter(TradingSettings.setting_key == key).first()
            current = setting.setting_value if setting else "(not set)"
            default = "true" if env == "local" else "false"
            effective = current if setting else default
            allows = effective.lower() == "true"

            status = "✅ ALLOWS" if allows else "❌ BLOCKS"
            print(f"  {key}: {current} → {status}")

            if args.set_true and env == "aws" and not allows:
                if setting:
                    setting.setting_value = "true"
                    db.commit()
                    print(f"    → Updated to 'true'")
                else:
                    new_setting = TradingSettings(setting_key=key, setting_value="true")
                    db.add(new_setting)
                    db.commit()
                    print(f"    → Created with value 'true'")
    finally:
        db.close()

    print()
    print("Done. Run again without --set-true to verify.")


if __name__ == "__main__":
    main()
