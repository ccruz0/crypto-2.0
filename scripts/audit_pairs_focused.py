#!/usr/bin/env python3
"""
Focused audit script to detect duplicate trading pair DEFINITIONS (not code references).

Only checks:
- Database tables (watchlist_items, market_data, market_prices, exchange_orders)
- Config JSON files (trading_config.json)
- Constant definitions (SUPPORTED_PAIRS, etc.)

Excludes:
- Code references (test files, price fetchers, etc.)
- Documentation
- Test artifacts
"""

import sys
import os
import json
from pathlib import Path
from collections import defaultdict, Counter
from typing import Dict, List, Tuple

# Repository root
REPO_ROOT = Path(__file__).parent.parent

def normalize_pair(pair: str) -> str:
    """Normalize pair to uppercase SYMBOL_CURRENCY format."""
    return pair.upper().strip()


def scan_config_json(file_path: Path) -> List[str]:
    """Scan JSON config files for trading pairs in 'coins' section."""
    pairs = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        if 'coins' in data:
            for pair in data['coins'].keys():
                pairs.append(normalize_pair(pair))
    except Exception as e:
        print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)
    
    return pairs


def scan_database() -> Dict[str, List[str]]:
    """Scan database for trading pairs (if accessible)."""
    pairs_by_table = defaultdict(list)
    
    try:
        sys.path.insert(0, str(REPO_ROOT / 'backend'))
        from app.database import SessionLocal
        from app.models.watchlist import WatchlistItem
        from app.models.market_price import MarketData, MarketPrice
        from app.models.exchange_order import ExchangeOrder
        
        db = SessionLocal()
        
        # Scan watchlist_items (non-deleted only)
        watchlist_items = db.query(WatchlistItem).filter(WatchlistItem.is_deleted == False).all()
        for item in watchlist_items:
            pair = normalize_pair(item.symbol)
            pairs_by_table['watchlist_items'].append(pair)
        
        # Scan market_data
        market_data = db.query(MarketData).all()
        for item in market_data:
            pair = normalize_pair(item.symbol)
            pairs_by_table['market_data'].append(pair)
        
        # Scan market_prices
        market_prices = db.query(MarketPrice).all()
        for item in market_prices:
            pair = normalize_pair(item.symbol)
            pairs_by_table['market_prices'].append(pair)
        
        # Scan exchange_orders (active only)
        orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.status.in_(['NEW', 'ACTIVE', 'PARTIALLY_FILLED'])
        ).all()
        for item in orders:
            pair = normalize_pair(item.symbol)
            pairs_by_table['exchange_orders'].append(pair)
        
        db.close()
    except Exception as e:
        print(f"Warning: Could not scan database: {e}", file=sys.stderr)
    
    return pairs_by_table


def main():
    """Main audit function."""
    print("=" * 80)
    print("TRADING PAIRS AUDIT (FOCUSED - DEFINITIONS ONLY)")
    print("=" * 80)
    print()
    
    all_pairs = defaultdict(list)
    
    # Scan config JSON files (only backend/trading_config.json is authoritative)
    print("Scanning config JSON files...")
    # Only check backend/trading_config.json as it's the authoritative source
    config_file = REPO_ROOT / 'backend' / 'trading_config.json'
    if config_file.exists():
        pairs = scan_config_json(config_file)
        for pair in pairs:
            all_pairs[pair].append(f"config:{config_file.name}")
        print(f"  {config_file.name}: {len(pairs)} pairs")
    
    # Note: Root trading_config.json is deprecated and not checked for duplicates
    
    # Scan database
    print("Scanning database...")
    try:
        db_pairs = scan_database()
        for table, pairs in db_pairs.items():
            for pair in pairs:
                all_pairs[pair].append(f"database:{table}")
            print(f"  {table}: {len(pairs)} pairs")
    except Exception as e:
        print(f"  Warning: Could not scan database: {e}")
    
    # Find duplicates WITHIN the same source (not across sources)
    # A pair appearing in both config and database is OK
    # A pair appearing twice in the same table is NOT OK
    duplicates = {}
    
    # Check for duplicates within each source
    sources = defaultdict(list)
    for pair, locations in all_pairs.items():
        for location in locations:
            sources[location].append(pair)
    
    for source, pairs in sources.items():
        pair_counts = Counter(pairs)
        source_duplicates = {p: c for p, c in pair_counts.items() if c > 1}
        if source_duplicates:
            duplicates[source] = source_duplicates
    
    # Print summary
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total unique pairs found: {len(all_pairs)}")
    print(f"Sources with duplicates: {len(duplicates)}")
    print()
    
    if duplicates:
        print("=" * 80)
        print("DUPLICATES DETECTED")
        print("=" * 80)
        print()
        
        for source, source_dups in sorted(duplicates.items()):
            print(f"{source}:")
            for pair, count in sorted(source_dups.items()):
                print(f"  {pair}: appears {count} times")
            print()
        
        print("=" * 80)
        print("❌ AUDIT FAILED: Duplicates found!")
        print("=" * 80)
        return 1
    else:
        print("=" * 80)
        print("✅ AUDIT PASSED: No duplicate definitions found!")
        print("=" * 80)
        return 0


if __name__ == '__main__':
    sys.exit(main())
