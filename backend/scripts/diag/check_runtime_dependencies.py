#!/usr/bin/env python3
"""
Runtime dependency check for agent/Telegram commands.
Run via: python backend/scripts/diag/check_runtime_dependencies.py
Or from container: docker exec <container> python /app/scripts/diag/check_runtime_dependencies.py
"""

import importlib
import os
import sys

modules = [
    "pydantic",
    "pydantic_settings",
    "requests",
]


def run_check() -> str:
    """Run dependency check and return output string. Callable from Telegram handler."""
    lines = ["Runtime dependency check", ""]
    for m in modules:
        try:
            importlib.import_module(m)
            lines.append(f"{m}: OK")
        except Exception as e:
            lines.append(f"{m}: FAILED -> {e}")

    env = "Docker" if os.path.exists("/.dockerenv") else "Local"
    lines.append("")
    lines.append(f"Runtime environment: {env}")
    return "\n".join(lines)


def main() -> int:
    output = run_check()
    print(output)
    failed = "FAILED" in output
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
