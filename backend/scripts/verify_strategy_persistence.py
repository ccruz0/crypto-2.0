#!/usr/bin/env python3
"""
Verify that dashboard strategy changes persist in the backend.
Simulates: 1) read config, 2) update coin preset (like PUT /coins/{symbol}), 3) re-read and assert.
Run from repo root: python backend/scripts/verify_strategy_persistence.py
"""
import json
import os
import sys
from pathlib import Path

# Add backend to path
backend = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend))
os.chdir(backend)

def main():
    from app.services.config_loader import load_config, save_config, CONFIG_PATH

    if not CONFIG_PATH or not CONFIG_PATH.exists():
        print("SKIP: No trading_config.json found (CONFIG_PATH not set or file missing). Create it by starting the backend once.")
        return 0

    print(f"Using config: {CONFIG_PATH}")
    cfg = load_config()
    coins = cfg.get("coins", {})

    # Pick a symbol to test (prefer one that exists)
    test_symbol = "ALGO_USDT"
    for sym in ["ALGO_USDT", "ETH_USDT", "BTC_USDT"]:
        if sym in coins or sym.replace("_USDT", "_USD") in coins:
            test_symbol = sym if sym in coins else sym.replace("_USDT", "_USD")
            break

    old_preset = None
    for k, v in coins.items():
        if k == test_symbol or k == test_symbol.replace("_USD", "_USDT"):
            old_preset = v.get("preset")
            break
    print(f"Current preset for {test_symbol}: {old_preset!r}")

    # Simulate dashboard: set to swing-conservative
    new_preset = "swing-conservative"
    cfg.setdefault("coins", {})[test_symbol] = {"preset": new_preset, "overrides": {}}
    save_config(cfg)
    print(f"Saved preset for {test_symbol} -> {new_preset!r}")

    # Re-read from disk (no cache)
    with open(CONFIG_PATH) as f:
        cfg2 = json.load(f)
    coins2 = cfg2.get("coins", {})
    got = coins2.get(test_symbol, {}).get("preset")
    if got != new_preset:
        # Try _USD variant
        alt = test_symbol.replace("_USDT", "_USD") if "_USDT" in test_symbol else test_symbol.replace("_USD", "_USDT")
        got = coins2.get(alt, {}).get("preset")
    if got != new_preset:
        print(f"FAIL: After re-read, coins[{test_symbol}].preset = {got!r} (expected {new_preset!r})")
        return 1
    print("OK: Config persisted; re-read preset matches.")

    # Restore original if we had one
    if old_preset is not None:
        cfg_restore = load_config()
        if test_symbol in cfg_restore.get("coins", {}):
            cfg_restore["coins"][test_symbol]["preset"] = old_preset
            save_config(cfg_restore)
            print(f"Restored {test_symbol} preset to {old_preset!r}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
