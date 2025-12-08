#!/usr/bin/env python3
"""
Audit script to detect duplicate trading pairs across the entire repository.

A trading pair is defined as: SYMBOL_CURRENCY (e.g., ADA_USDT, ETH_USD).
Pairs may exist across: DB tables, backend models, config JSON, frontend constants, etc.

It is acceptable for a symbol to appear with different quote currencies (e.g., ADA/USDT and ADA/USD),
but NOT acceptable for ADA/USDT to appear more than once in any location.
"""

import os
import re
import json
import sys
from pathlib import Path
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Set
import sqlite3

# Repository root
REPO_ROOT = Path(__file__).parent.parent

# Pattern to match trading pairs: SYMBOL_CURRENCY format
PAIR_PATTERN = re.compile(r'\b([A-Z0-9]+)_(USDT|USD|BTC|ETH|EUR|GBP|JPY|CNY)\b')

# Files/directories to exclude
EXCLUDE_PATTERNS = [
    'node_modules',
    '.git',
    '__pycache__',
    'venv',
    'env',
    '.venv',
    'dist',
    'build',
    '.next',
    'coverage',
    '.pytest_cache',
    '*.pyc',
    '*.pyo',
    '*.egg-info',
    'playwright-report',
    'test-results',
    'artifacts',
    '*.md',  # Documentation files
    '*.bak',
    '*.backup',
    '*.old',
]


def normalize_pair(pair: str) -> str:
    """Normalize pair to uppercase SYMBOL_CURRENCY format."""
    return pair.upper().strip()


def extract_pairs_from_text(text: str, file_path: str) -> List[Tuple[str, int]]:
    """Extract trading pairs from text content."""
    pairs = []
    for match in PAIR_PATTERN.finditer(text):
        pair = normalize_pair(match.group(0))
        line_num = text[:match.start()].count('\n') + 1
        pairs.append((pair, line_num))
    return pairs


def scan_file(file_path: Path) -> List[Tuple[str, int]]:
    """Scan a single file for trading pairs."""
    try:
        # Skip markdown and other documentation
        if file_path.suffix in ['.md', '.txt', '.log']:
            return []
        
        # Only scan code and config files
        if file_path.suffix in ['.py', '.ts', '.tsx', '.js', '.jsx', '.json', '.sql']:
            # Skip test artifacts and reports
            if any(exclude in str(file_path) for exclude in ['playwright-report', 'test-results', 'artifacts', '.bak', '.backup']):
                return []
            
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                return extract_pairs_from_text(content, str(file_path))
    except Exception as e:
        print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)
    return []


def scan_directory(directory: Path) -> Dict[str, List[Tuple[str, int]]]:
    """Scan directory recursively for trading pairs."""
    pairs_by_file = defaultdict(list)
    
    for root, dirs, files in os.walk(directory):
        # Filter out excluded directories
        dirs[:] = [d for d in dirs if not any(exclude in d for exclude in EXCLUDE_PATTERNS)]
        
        for file in files:
            file_path = Path(root) / file
            
            # Skip excluded files
            if any(exclude in str(file_path) for exclude in EXCLUDE_PATTERNS):
                continue
            
            pairs = scan_file(file_path)
            if pairs:
                pairs_by_file[str(file_path.relative_to(REPO_ROOT))] = pairs
    
    return pairs_by_file


def scan_database() -> Dict[str, List[Tuple[str, int]]]:
    """Scan database for trading pairs (if accessible)."""
    pairs_by_table = defaultdict(list)
    
    try:
        # Try to import database models
        sys.path.insert(0, str(REPO_ROOT / 'backend'))
        from app.database import SessionLocal
        from app.models.watchlist import WatchlistItem
        from app.models.market_price import MarketData, MarketPrice
        from app.models.exchange_order import ExchangeOrder
        
        db = SessionLocal()
        
        # Scan watchlist_items
        watchlist_items = db.query(WatchlistItem).all()
        for item in watchlist_items:
            pair = normalize_pair(item.symbol)
            pairs_by_table['watchlist_items'].append((pair, item.id))
        
        # Scan market_data
        market_data = db.query(MarketData).all()
        for item in market_data:
            pair = normalize_pair(item.symbol)
            pairs_by_table['market_data'].append((pair, item.id))
        
        # Scan market_prices
        market_prices = db.query(MarketPrice).all()
        for item in market_prices:
            pair = normalize_pair(item.symbol)
            pairs_by_table['market_prices'].append((pair, item.id))
        
        # Scan exchange_orders
        orders = db.query(ExchangeOrder).all()
        for item in orders:
            pair = normalize_pair(item.symbol)
            pairs_by_table['exchange_orders'].append((pair, item.id))
        
        db.close()
    except Exception as e:
        print(f"Warning: Could not scan database: {e}", file=sys.stderr)
    
    return pairs_by_table


def scan_config_json(file_path: Path) -> Dict[str, List[Tuple[str, int]]]:
    """Scan JSON config files for trading pairs in 'coins' section."""
    pairs_by_file = defaultdict(list)
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        if 'coins' in data:
            for pair, config in data['coins'].items():
                normalized = normalize_pair(pair)
                # Use line number 0 for JSON keys (we can't easily get exact line)
                pairs_by_file[str(file_path.relative_to(REPO_ROOT))].append((normalized, 0))
    except Exception as e:
        print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)
    
    return pairs_by_file


def generate_report(pairs_by_location: Dict[str, List[Tuple[str, int]]]) -> Tuple[Dict, Dict]:
    """Generate duplicate report."""
    # Count occurrences per pair
    pair_counts = Counter()
    pair_locations = defaultdict(list)
    
    for location, pairs in pairs_by_location.items():
        for pair, line_num in pairs:
            pair_counts[pair] += 1
            pair_locations[pair].append((location, line_num))
    
    # Find duplicates (pairs that appear more than once)
    duplicates = {pair: (count, locations) 
                 for pair, count in pair_counts.items() 
                 if count > 1
                 for locations in [pair_locations[pair]]}
    
    return pair_counts, duplicates


def main():
    """Main audit function."""
    print("=" * 80)
    print("TRADING PAIRS AUDIT")
    print("=" * 80)
    print()
    print("Focus: Detecting duplicate DEFINITIONS (not code references)")
    print("=" * 80)
    print()
    
    pairs_by_location = {}
    
    # Scan config JSON files (only backend/trading_config.json is authoritative)
    print("Scanning config JSON files...")
    config_file = REPO_ROOT / 'backend' / 'trading_config.json'
    if config_file.exists():
        config_pairs = scan_config_json(config_file)
        pairs_by_location.update(config_pairs)
        print(f"  Scanned {config_file.name}: {len(config_pairs.get(str(config_file.relative_to(REPO_ROOT)), []))} pairs")
    
    # Scan database (authoritative definitions)
    print("Scanning database...")
    try:
        db_pairs = scan_database()
        for table, pairs in db_pairs.items():
            pairs_by_location[f"database:{table}"] = pairs
        print(f"  Scanned {len(db_pairs)} database tables")
        for table, pairs in db_pairs.items():
            print(f"    {table}: {len(pairs)} pairs")
    except Exception as e:
        print(f"  Warning: Could not scan database: {e}")
    
    # Generate report - check for duplicates WITHIN each source
    print()
    print("Generating report...")
    pair_counts, all_duplicates = generate_report(pairs_by_location)
    
    # Filter to only duplicates within the same source (not across sources)
    # A pair appearing in both config and database is OK
    # A pair appearing twice in the same table/file is NOT OK
    source_duplicates = defaultdict(dict)
    
    for location, pairs in pairs_by_location.items():
        # Count pairs within this location
        location_pair_counts = Counter(pair for pair, _ in pairs)
        location_dups = {p: c for p, c in location_pair_counts.items() if c > 1}
        if location_dups:
            source_duplicates[location] = location_dups
    
    # Print summary
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total unique pairs found: {len(pair_counts)}")
    print(f"Total pair occurrences: {sum(pair_counts.values())}")
    print(f"Sources with internal duplicates: {len(source_duplicates)}")
    print()
    
    if source_duplicates:
        print("=" * 80)
        print("DUPLICATES DETECTED (within same source)")
        print("=" * 80)
        print()
        
        for location, dups in sorted(source_duplicates.items()):
            print(f"{location}:")
            for pair, count in sorted(dups.items()):
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
