#!/usr/bin/env python3
import json
import sys

try:
    with open("trading_config.json") as f:
        config = json.load(f)
    
    has_sr = "strategy_rules" in config
    print(f"Has strategy_rules: {has_sr}")
    
    if has_sr:
        sr = config["strategy_rules"]
        print(f"Presets: {list(sr.keys())}")
        swing = sr.get("swing", {})
        if swing and "rules" in swing:
            cons = swing["rules"].get("Conservative", {})
            print(f"swing/Conservative volumeMinRatio: {cons.get('volumeMinRatio')}")
    else:
        print("No strategy_rules found")
        presets = config.get("presets", {})
        if presets:
            swing = presets.get("swing", {})
            if swing and "rules" in swing:
                cons = swing["rules"].get("Conservative", {})
                print(f"presets/swing/Conservative volumeMinRatio: {cons.get('volumeMinRatio')}")
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
