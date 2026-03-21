#!/usr/bin/env python3
"""CLI to configure Claw and ATP Telegram credentials (no GUI required)."""

import sys
from pathlib import Path


FIELDS = [
    ("TELEGRAM_CLAW_BOT_TOKEN", "Claw bot token (@Claw_cruz_bot)"),
    ("TELEGRAM_CLAW_CHAT_ID", "Claw chat ID"),
    ("TELEGRAM_BOT_TOKEN", "ATP bot token"),
    ("TELEGRAM_CHAT_ID", "ATP chat ID"),
]


def main():
    print("Claw / ATP Config Assistant (CLI)\n")
    values = {}
    for key, label in FIELDS:
        val = input(f"{label} ({key}): ").strip()
        values[key] = val

    out_path = Path.cwd() / ".env.claw_atp"
    lines = [f"{k}={v}" for k, v in values.items() if v]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nSaved to {out_path}")
    print("To use: source .env.claw_atp  (or copy into .env / secrets/runtime.env)")


if __name__ == "__main__":
    main()
