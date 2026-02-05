#!/usr/bin/env python3
"""
Sync trading_config.json coins so every watchlist symbol has preset = resolved strategy_key.
This makes dashboard and backend show the same strategy for all coins.
Run from repo root: PYTHONPATH=backend python backend/scripts/sync_strategy_config.py
Optional: --dry-run (print only, no write), --yes (skip confirm).
"""
import argparse
import os
import sys
from pathlib import Path

backend = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend))
os.chdir(backend)


def main():
    parser = argparse.ArgumentParser(description="Sync config coins to resolved strategy per symbol")
    parser.add_argument("--dry-run", action="store_true", help="Print changes only, do not write config")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    from app.database import SessionLocal
    from app.models.watchlist import WatchlistItem
    from app.services.config_loader import load_config, save_config
    from app.services.strategy_profiles import resolve_strategy_profile
    from app.services.signal_throttle import build_strategy_key

    db = SessionLocal()
    try:
        items = db.query(WatchlistItem).filter(WatchlistItem.is_deleted == False).all()
        cfg = load_config()
        coins = cfg.get("coins", {})
        updates = []
        for item in items:
            symbol = (item.symbol or "").upper()
            if not symbol:
                continue
            try:
                strategy_type, risk_approach = resolve_strategy_profile(symbol, db, item)
                # Config and API use hyphen (swing-conservative); build_strategy_key uses colon
                raw = build_strategy_key(strategy_type, risk_approach)
                resolved_key = raw.replace(":", "-") if ":" in raw else raw
            except Exception as e:
                print(f"  Skip {symbol}: resolve failed: {e}", file=sys.stderr)
                continue
            current = None
            for k, v in coins.items():
                if k == symbol or k == symbol.replace("_USDT", "_USD") or k == symbol.replace("_USD", "_USDT"):
                    current = v.get("preset")
                    break
            if current != resolved_key:
                updates.append((symbol, current, resolved_key))
                existing = coins.get(symbol) or coins.get(symbol.replace("_USDT", "_USD")) or coins.get(symbol.replace("_USD", "_USDT")) or {}
                overrides = existing.get("overrides", {}) if isinstance(existing, dict) else {}
                coins[symbol] = {"preset": resolved_key, "overrides": overrides}

        if not updates:
            print("No changes needed; config already matches resolved strategy for all watchlist symbols.")
            return 0

        print("Updates to apply:")
        for sym, old, new in updates:
            print(f"  {sym}: {old!r} -> {new!r}")
        if args.dry_run:
            print("(dry-run: not writing config)")
            return 0
        if not args.yes:
            try:
                r = input("Write trading_config.json? [y/N]: ").strip().lower()
                if r != "y" and r != "yes":
                    print("Aborted.")
                    return 1
            except (EOFError, KeyboardInterrupt):
                print("Aborted.")
                return 1
        save_config(cfg)
        try:
            from app.services.strategy_profiles import invalidate_config_cache
            invalidate_config_cache()
        except Exception:
            pass
        print(f"Updated {len(updates)} coins in trading_config.json. Dashboard and backend will show the same strategies.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
