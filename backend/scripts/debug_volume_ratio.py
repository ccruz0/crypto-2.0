#!/usr/bin/env python3
"""
Debug script to verify volumeMinRatio persistence flow.

This script:
1. Calls GET /api/config to retrieve current config
2. Extracts and prints all volumeMinRatio values per preset & risk mode
3. Verifies the structure is correct
"""

import json
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.config_loader import load_config, get_strategy_rules

def main():
    print("=" * 60)
    print("VOLUME MIN RATIO PERSISTENCE AUDIT")
    print("=" * 60)
    
    # Load config from file
    cfg = load_config()
    
    # Check strategy_rules first (new format)
    strategy_rules = cfg.get("strategy_rules", {})
    if not strategy_rules:
        # Fallback to presets (legacy format)
        strategy_rules = cfg.get("presets", {})
        print("⚠️  Using 'presets' structure (legacy format)")
    else:
        print("✅ Using 'strategy_rules' structure (new format)")
    
    print("\n📊 VolumeMinRatio values in config file:")
    print("-" * 60)
    
    all_presets = ["swing", "intraday", "scalp"]
    all_risk_modes = ["Conservative", "Aggressive"]
    
    found_any = False
    for preset_name in all_presets:
        preset_data = strategy_rules.get(preset_name, {})
        if not preset_data:
            print(f"  {preset_name}: ❌ Not found")
            continue
        
        if "rules" not in preset_data:
            print(f"  {preset_name}: ❌ No 'rules' structure")
            continue
        
        for risk_mode in all_risk_modes:
            rules = preset_data.get("rules", {}).get(risk_mode, {})
            vol_ratio = rules.get("volumeMinRatio")
            if vol_ratio is not None:
                found_any = True
                print(f"  {preset_name}/{risk_mode}: volumeMinRatio = {vol_ratio}")
            else:
                print(f"  {preset_name}/{risk_mode}: ❌ volumeMinRatio missing")
    
    if not found_any:
        print("  ⚠️  No volumeMinRatio values found in config!")
    
    print("\n" + "=" * 60)
    print("Testing get_strategy_rules() function:")
    print("-" * 60)
    
    for preset_name in all_presets:
        for risk_mode in all_risk_modes:
            rules = get_strategy_rules(preset_name, risk_mode)
            vol_ratio = rules.get("volumeMinRatio")
            print(f"  get_strategy_rules('{preset_name}', '{risk_mode}') -> volumeMinRatio = {vol_ratio}")
    
    print("\n" + "=" * 60)
    print("✅ Audit complete")
    print("=" * 60)

if __name__ == "__main__":
    main()
