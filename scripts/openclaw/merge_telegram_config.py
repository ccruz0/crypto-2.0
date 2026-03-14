#!/usr/bin/env python3
"""Merge channels.telegram into OpenClaw config. Run on LAB."""
import json
import os
import sys

path = os.environ.get("OPENCLAW_CONFIG_PATH", "/opt/openclaw/home-data/openclaw.json")
cfg = {}
if os.path.exists(path):
    with open(path) as f:
        cfg = json.load(f)

channels = cfg.setdefault("channels", {})
tg = channels.setdefault("telegram", {})
tg["enabled"] = True
tg["dmPolicy"] = tg.get("dmPolicy", "pairing")

with open(path, "w") as f:
    json.dump(cfg, f, indent=2)

print("Updated", path)
print("channels.telegram.enabled:", tg.get("enabled"))
