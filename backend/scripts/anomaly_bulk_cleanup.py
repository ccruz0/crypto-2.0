#!/usr/bin/env python3
"""
One-time bulk cleanup for historical duplicate anomaly tasks.

Default mode is dry-run. Use --apply to execute status updates.
"""

import argparse
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk cleanup duplicate anomaly tasks in Notion.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default is dry-run).",
    )
    args = parser.parse_args()

    from app.services.agent_anomaly_detector import run_anomaly_bulk_cleanup

    result = run_anomaly_bulk_cleanup(dry_run=not args.apply)
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

