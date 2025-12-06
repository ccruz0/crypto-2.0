#!/usr/bin/env python3
"""
Debug script to check volumeMinRatio persistence in config file.
"""
import json
import sys
from pathlib import Path

CONFIG_PATH = Path("trading_config.json")
if not CONFIG_PATH.exists():
    CONFIG_PATH = Path("backend/trading_config.json")

if not CONFIG_PATH.exists():
    print("ERROR: trading_config.json not found")
    sys.exit(1)

with open(CONFIG_PATH) as f:
    config = json.load(f)

print("=" * 60)
print("VOLUME MIN RATIO PERSISTENCE DEBUG")
print("=" * 60)

# Check strategy_rules
strategy_rules = config.get("strategy_rules", {})
print(f"\nHas strategy_rules: {bool(strategy_rules)}")
print(f"Presets in strategy_rules: {list(strategy_rules.keys())}")

if strategy_rules:
    for preset_name, preset_data in strategy_rules.items():
        print(f"\n--- {preset_name} ---")
        if isinstance(preset_data, dict) and "rules" in preset_data:
            rules = preset_data.get("rules", {})
            for risk_mode, rule in rules.items():
                if isinstance(rule, dict):
                    vol_ratio = rule.get("volumeMinRatio")
                    print(f"  {risk_mode}: volumeMinRatio = {vol_ratio} (type: {type(vol_ratio).__name__})")
                    # Show all keys in rule
                    print(f"    All keys in rule: {list(rule.keys())}")
        else:
            print(f"  No 'rules' structure found")
else:
    print("\n⚠️  strategy_rules is empty or missing!")
    print("Checking presets (legacy format)...")
    presets = config.get("presets", {})
    for preset_name, preset_data in presets.items():
        if isinstance(preset_data, dict) and "rules" in preset_data:
            rules = preset_data.get("rules", {})
            for risk_mode, rule in rules.items():
                if isinstance(rule, dict):
                    vol_ratio = rule.get("volumeMinRatio")
                    print(f"  {preset_name}/{risk_mode}: volumeMinRatio = {vol_ratio}")

print("\n" + "=" * 60)
