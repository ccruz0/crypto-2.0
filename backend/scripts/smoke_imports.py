#!/usr/bin/env python3
"""Minimal smoke check: import app.main and app.services.exchange_sync without errors."""
import sys
from pathlib import Path

# Ensure backend is on path when run as script (backend or repo root)
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

def main():
    try:
        import app.main as _  # noqa: F401
        print("OK: app.main imports")
    except Exception as e:
        print(f"FAIL: app.main import error: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        import app.services.exchange_sync as _  # noqa: F401
        print("OK: app.services.exchange_sync imports")
    except Exception as e:
        print(f"FAIL: app.services.exchange_sync import error: {e}", file=sys.stderr)
        sys.exit(1)
    print("OK: smoke_imports passed")

if __name__ == "__main__":
    main()
