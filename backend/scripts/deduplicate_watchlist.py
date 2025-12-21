#!/usr/bin/env python3
"""Utility script to deduplicate watchlist_items in the database."""
import argparse
import logging
import os
import sys

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.database import SessionLocal  # noqa: E402
from app.services.watchlist_selector import cleanup_watchlist_duplicates  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deduplicate watchlist_items table")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze duplicates without committing changes",
    )
    parser.add_argument(
        "--hard-delete",
        action="store_true",
        help="Physically delete duplicate rows instead of marking is_deleted=True (requires --confirm-hard-delete)",
    )
    parser.add_argument(
        "--confirm-hard-delete",
        action="store_true",
        help="Acknowledge risks of hard delete; required when using --hard-delete",
    )
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()

    if args.hard_delete and not args.confirm_hard_delete:
        raise SystemExit(
            "⚠️ Hard delete requires --confirm-hard-delete. "
            "Use soft-delete defaults unless you are certain there are no references."
        )

    session = SessionLocal()
    try:
        summary = cleanup_watchlist_duplicates(
            session,
            dry_run=args.dry_run,
            soft_delete=not args.hard_delete,
        )
        info_label = "[DRY RUN] " if args.dry_run else ""
        logging.info(
            "%sWatchlist dedup summary: scanned=%s canonical=%s duplicates_cleaned=%s hard_delete=%s",
            info_label,
            summary.get("scanned"),
            summary.get("canonical"),
            summary.get("duplicates"),
            args.hard_delete,
        )
    finally:
        try:
            if args.dry_run:
                session.rollback()
        finally:
            session.close()


if __name__ == "__main__":
    main()
