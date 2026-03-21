#!/usr/bin/env python3
"""
Verify that trading alerts are routed to ATP Alerts (TELEGRAM_CHAT_ID_TRADING).

Run inside backend container on EC2 to confirm runtime config:
  docker compose --profile aws exec backend-aws python scripts/verify_trading_telegram_routing.py

Or from repo root with same env:
  cd backend && python scripts/verify_trading_telegram_routing.py

Output:
  - Effective trading chat_id (what send_message uses for chat_destination="trading")
  - Config source (TELEGRAM_CHAT_ID_TRADING vs fallbacks)
  - Whether it matches ATP Alerts (-1003820753438)
  - Optional: send a test trading alert
"""
import os
import sys
from pathlib import Path

# Ensure app is importable
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Load env files when running from host. In container, docker-compose injects env.
REPO_ROOT = BACKEND.parent
for base in [REPO_ROOT, Path("/app")]:
    for f in [".env", ".env.aws", "secrets/runtime.env"]:
        p = base / f
        if p.exists():
            try:
                with open(p) as fp:
                    for line in fp:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, _, v = line.partition("=")
                            k, v = k.strip(), v.strip().strip('"\'')
                            if k and v and k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass

# Must set ENVIRONMENT=aws for AWS path in refresh_config
if "ENVIRONMENT" not in os.environ:
    os.environ["ENVIRONMENT"] = "aws"
if "RUNTIME_ORIGIN" not in os.environ:
    os.environ["RUNTIME_ORIGIN"] = "AWS"

ATP_ALERTS_CHAT_ID = "-1003820753438"


def main():
    from app.services.telegram_notifier import telegram_notifier
    from app.core.environment import getRuntimeEnv

    print("=" * 60)
    print("TRADING TELEGRAM ROUTING VERIFICATION")
    print("=" * 60)

    # Raw env values (for debugging)
    chat_trading = (os.getenv("TELEGRAM_CHAT_ID_TRADING") or "").strip()
    chat_aws = (os.getenv("TELEGRAM_CHAT_ID_AWS") or "").strip()
    chat_generic = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()

    print("\n1. ENV VAR SOURCES (raw)")
    print(f"   TELEGRAM_CHAT_ID_TRADING = {chat_trading or '(not set)'}")
    print(f"   TELEGRAM_CHAT_ID_AWS      = {chat_aws or '(not set)'}")
    print(f"   TELEGRAM_CHAT_ID          = {chat_generic or '(not set)'}")

    # Resolve via refresh_config (same logic as send_message)
    cfg = telegram_notifier.refresh_config()
    runtime_env = getRuntimeEnv()

    print("\n2. RUNTIME CONFIG (from refresh_config)")
    print(f"   runtime_env       = {runtime_env}")
    print(f"   enabled           = {cfg.get('enabled')}")
    print(f"   block_reasons     = {cfg.get('block_reasons') or []}")

    # Effective trading chat_id (exact logic from send_message)
    _chat_id_trading = getattr(telegram_notifier, "_chat_id_trading", None)
    effective = _chat_id_trading or telegram_notifier.chat_id

    print("\n3. EFFECTIVE TRADING CHAT ID (used at send time)")
    print(f"   _chat_id_trading  = {_chat_id_trading or '(none)'}")
    print(f"   chat_id (fallback)= {telegram_notifier.chat_id or '(none)'}")
    print(f"   effective_chat_id = {effective or '(none)'}")

    print("\n4. ATP ALERTS CHECK")
    if effective == ATP_ALERTS_CHAT_ID:
        print(f"   ✅ MATCH: Trading alerts route to ATP Alerts ({ATP_ALERTS_CHAT_ID})")
    elif effective:
        print(f"   ⚠️  MISMATCH: effective={effective} expected={ATP_ALERTS_CHAT_ID}")
        print("   FIX: Set TELEGRAM_CHAT_ID_TRADING=-1003820753438 in secrets/runtime.env or .env.aws")
        print("        Then: docker compose --profile aws restart backend-aws market-updater-aws")
    else:
        print("   ❌ NO CHAT ID: Trading alerts will not send (chat_id missing)")
        print("   FIX: Set TELEGRAM_CHAT_ID_TRADING=-1003820753438 in secrets/runtime.env or .env.aws")

    # Optional test send
    if "--send-test" in sys.argv and effective and cfg.get("enabled"):
        print("\n5. SENDING TEST TRADING ALERT")
        ok = telegram_notifier.send_message(
            "[TEST] Trading routing verification — ATP Alerts",
            origin="TEST",
            chat_destination="trading",
        )
        print(f"   Result: {'✅ SENT' if ok else '❌ FAILED'}")
        if ok:
            print("   Check ATP Alerts channel for the test message.")
    elif "--send-test" in sys.argv:
        print("\n5. SKIP TEST SEND (enabled=False or no chat_id)")

    print("\n" + "=" * 60)
    return 0 if effective == ATP_ALERTS_CHAT_ID else 1


if __name__ == "__main__":
    sys.exit(main())
