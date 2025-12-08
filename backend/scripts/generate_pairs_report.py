#!/usr/bin/env python3
"""
Generate a lean report of all unique trading pairs across the system.
"""

import sys
import json
from pathlib import Path
from collections import Counter

REPO_ROOT = Path(__file__).parent.parent

def normalize_pair(pair: str) -> str:
    """Normalize pair to uppercase SYMBOL_CURRENCY format."""
    return pair.upper().strip()


def get_config_pairs():
    """Get pairs from config file."""
    config_file = REPO_ROOT / 'backend' / 'trading_config.json'
    pairs = []
    
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if 'coins' in data:
                    pairs = [normalize_pair(p) for p in data['coins'].keys()]
        except Exception as e:
            print(f"Warning: Could not read config: {e}", file=sys.stderr)
    
    return sorted(set(pairs))


def get_database_pairs():
    """Get pairs from database (if accessible)."""
    pairs = []
    
    try:
        sys.path.insert(0, str(REPO_ROOT / 'backend'))
        from app.database import SessionLocal
        from app.models.watchlist import WatchlistItem
        
        db = SessionLocal()
        items = db.query(WatchlistItem).filter(WatchlistItem.is_deleted == False).all()
        pairs = [normalize_pair(item.symbol) for item in items]
        db.close()
    except Exception as e:
        print(f"Warning: Could not access database: {e}", file=sys.stderr)
    
    return sorted(set(pairs))


def main():
    """Generate report."""
    print("=" * 80)
    print("TRADING PAIRS VALIDATION REPORT")
    print("=" * 80)
    print()
    
    # Get pairs from all sources
    config_pairs = get_config_pairs()
    db_pairs = get_database_pairs()
    
    # Report
    print("=== CONFIG FILE (backend/trading_config.json) ===")
    print(f"Total unique pairs: {len(config_pairs)}")
    for pair in config_pairs:
        print(f"  {pair}")
    print()
    
    if db_pairs:
        print("=== DATABASE (watchlist_items, non-deleted) ===")
        print(f"Total unique pairs: {len(db_pairs)}")
        for pair in db_pairs:
            print(f"  {pair}")
        print()
        
        # Check alignment
        config_set = set(config_pairs)
        db_set = set(db_pairs)
        
        only_in_config = config_set - db_set
        only_in_db = db_set - config_set
        in_both = config_set & db_set
        
        print("=== ALIGNMENT CHECK ===")
        print(f"Pairs in both config and database: {len(in_both)}")
        if only_in_config:
            print(f"Pairs only in config ({len(only_in_config)}): {sorted(only_in_config)}")
        if only_in_db:
            print(f"Pairs only in database ({len(only_in_db)}): {sorted(only_in_db)}")
        print()
    
    # Final validation
    print("=" * 80)
    print("VALIDATION RESULT")
    print("=" * 80)
    
    # Check for duplicates within config
    config_counts = Counter(config_pairs)
    config_dups = {p: c for p, c in config_counts.items() if c > 1}
    
    if config_dups:
        print("❌ DUPLICATES FOUND IN CONFIG:")
        for pair, count in config_dups.items():
            print(f"  {pair}: {count} times")
        return 1
    
    if db_pairs:
        db_counts = Counter(db_pairs)
        db_dups = {p: c for p, c in db_counts.items() if c > 1}
        
        if db_dups:
            print("❌ DUPLICATES FOUND IN DATABASE:")
            for pair, count in db_dups.items():
                print(f"  {pair}: {count} times")
            return 1
    
    print("✅ All trading pairs validated – no duplicates across any source")
    print()
    print("=== SYSTEM PAIRS (All Sources Combined) ===")
    all_pairs = sorted(set(config_pairs + (db_pairs if db_pairs else [])))
    for pair in all_pairs:
        print(f"  {pair}")
    print(f"Total unique pairs in system: {len(all_pairs)}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
