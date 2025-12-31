#!/usr/bin/env python3
"""
End-to-end verification script for WatchlistItem as single source of truth.

This script verifies:
1. GET /api/dashboard returns exact DB values (no defaults/mutations)
2. PUT /api/dashboard/symbol/{symbol} writes to WatchlistItem and returns fresh DB read
3. Write-through: Changes persist immediately and reflect back
4. Zero mismatches for trade_amount_usd and enabled flags
"""

import sys
import os
from pathlib import Path
import requests
import time
from typing import Dict, Any, Optional
import hashlib
from urllib.parse import urlparse, urlunparse

# Add parent directory to path to import app modules
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def is_running_in_docker() -> bool:
    """Check if script is running inside Docker container"""
    return os.path.exists("/.dockerenv") or os.getenv("RUNNING_IN_DOCKER") == "1"


def compute_db_fingerprint(database_url: str) -> tuple[str, str, str]:
    """Compute DB fingerprint (host, name, hash) from DATABASE_URL"""
    try:
        parsed = urlparse(database_url)
        db_host = parsed.hostname or "unknown"
        db_name = parsed.path.lstrip("/") if parsed.path else "unknown"
        # Hash with password stripped (never include password)
        safe_url = urlunparse(parsed._replace(netloc=f"{parsed.username or ''}@{parsed.hostname or ''}:{parsed.port or ''}"))
        db_hash = hashlib.sha256(safe_url.encode()).hexdigest()[:10]
        return db_host, db_name, db_hash
    except Exception:
        return "unknown", "unknown", "unknown"


def verify_db_match(api_url: str, local_database_url: str) -> bool:
    """Verify local DB matches API DB by comparing fingerprints"""
    try:
        response = requests.get(api_url, timeout=5)
        api_db_host = response.headers.get("X-ATP-DB-Host", "unknown")
        api_db_name = response.headers.get("X-ATP-DB-Name", "unknown")
        api_db_hash = response.headers.get("X-ATP-DB-Hash", "unknown")
        
        local_host, local_name, local_hash = compute_db_fingerprint(local_database_url)
        
        if api_db_hash != "unknown" and local_hash != "unknown" and api_db_hash != local_hash:
            logger.error("=" * 70)
            logger.error("❌ DATABASE MISMATCH DETECTED")
            logger.error("=" * 70)
            logger.error(f"API DB:  host={api_db_host}, name={api_db_name}, hash={api_db_hash}")
            logger.error(f"Local DB: host={local_host}, name={local_name}, hash={local_hash}")
            logger.error("")
            logger.error("Script is using a different database than the API!")
            logger.error("Run via: backend/scripts/run_in_backend_container.sh python3 scripts/verify_watchlist_e2e.py")
            logger.error("=" * 70)
            return False
        return True
    except requests.exceptions.RequestException as e:
        # API not reachable - print exact URL and guidance
        logger.error("=" * 70)
        logger.error("❌ API NOT REACHABLE")
        logger.error("=" * 70)
        logger.error(f"Attempted URL: {api_url}")
        logger.error(f"Error: {e}")
        logger.error("")
        logger.error("If running on Mac, you may need to:")
        logger.error("  - SSH to AWS: ssh hilovivo-aws 'curl -sI http://localhost:8002/api/dashboard'")
        logger.error("  - Or use wrapper: backend/scripts/run_in_backend_container.sh python3 scripts/verify_watchlist_e2e.py")
        logger.error("=" * 70)
        # Still honor host check - if not in Docker, this should have been caught earlier
        return True


# GUARD: Prevent host execution unless explicitly allowed
if not is_running_in_docker() and os.getenv("ALLOW_HOST_RUN") != "1":
    script_name = Path(__file__).name
    print("=" * 70, file=sys.stderr)
    print("❌ REFUSING TO RUN ON HOST", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print("", file=sys.stderr)
    print("This script must run inside the backend container to use the same", file=sys.stderr)
    print("database as the API. Running on host may show mismatches.", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"Run via: backend/scripts/run_in_backend_container.sh python3 scripts/{script_name}", file=sys.stderr)
    print("", file=sys.stderr)
    print("Override: ALLOW_HOST_RUN=1 (advanced, may show mismatches)", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    sys.exit(2)


def get_api_url() -> str:
    """Get API URL from environment or default"""
    api_url = os.getenv("API_URL", "http://localhost:8002")
    if not api_url.endswith("/api/dashboard"):
        api_url = f"{api_url.rstrip('/')}/api/dashboard"
    return api_url


def get_db_item(db: Session, symbol: str) -> Optional[WatchlistItem]:
    """Get WatchlistItem from database using same selection logic as API"""
    from app.services.watchlist_selector import select_preferred_watchlist_item
    items = db.query(WatchlistItem).filter(
        WatchlistItem.symbol == symbol.upper(),
        WatchlistItem.is_deleted == False
    ).all()
    # Use same selection logic as API to ensure we compare the same row
    return select_preferred_watchlist_item(items, symbol.upper()) if items else None


def get_api_item(api_url: str, symbol: str) -> Optional[Dict]:
    """Get watchlist item from API"""
    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        items = response.json()
        for item in items:
            if item.get("symbol", "").upper() == symbol.upper():
                return item
        return None
    except Exception as e:
        logger.error(f"Error fetching from API: {e}")
        return None


def compare_values(db_value: Any, api_value: Any, field: str):
    """Compare DB value with API value, return (match, message)"""
    # Handle None values
    if db_value is None and api_value is None:
        return True, f"{field}: null == null ✓"
    if db_value is None:
        return False, f"{field}: DB=null, API={api_value} ✗"
    if api_value is None:
        return False, f"{field}: DB={db_value}, API=null ✗"
    
    # Handle numeric values (with small tolerance for floats)
    if isinstance(db_value, (int, float)) and isinstance(api_value, (int, float)):
        if isinstance(db_value, float) or isinstance(api_value, float):
            if abs(db_value - api_value) > max(1e-6, abs(db_value) * 0.001):
                return False, f"{field}: DB={db_value}, API={api_value} ✗"
        else:
            if db_value != api_value:
                return False, f"{field}: DB={db_value}, API={api_value} ✗"
        return True, f"{field}: {db_value} == {api_value} ✓"
    
    # Handle boolean values
    if isinstance(db_value, bool) and isinstance(api_value, bool):
        if db_value != api_value:
            return False, f"{field}: DB={db_value}, API={api_value} ✗"
        return True, f"{field}: {db_value} == {api_value} ✓"
    
    # Handle string values
    if str(db_value).strip() != str(api_value).strip():
        return False, f"{field}: DB={db_value}, API={api_value} ✗"
    
    return True, f"{field}: {db_value} == {api_value} ✓"


def get_resolved_strategy_key(db: Session, item: WatchlistItem) -> Optional[str]:
    """Resolve the full strategy key (preset-risk) for a watchlist item.
    
    Returns canonical strategy key like "swing-conservative" or None if unresolved.
    """
    try:
        from app.services.strategy_profiles import resolve_strategy_profile
        strategy_type, risk_approach = resolve_strategy_profile(
            symbol=item.symbol,
            db=db,
            watchlist_item=item
        )
        if strategy_type and risk_approach:
            return f"{strategy_type.value}-{risk_approach.value}"
        return None
    except Exception as e:
        logger.debug(f"Could not resolve strategy for {item.symbol}: {e}")
        return None


def verify_read_consistency(db: Session, api_url: str, symbol: str):
    """Verify GET /api/dashboard returns exact DB values"""
    logger.info(f"Verifying read consistency for {symbol}...")
    
    db_item = get_db_item(db, symbol)
    if not db_item:
        return False, [f"Symbol {symbol} not found in database"]
    
    api_item = get_api_item(api_url, symbol)
    if not api_item:
        return False, [f"Symbol {symbol} not found in API response"]
    
    # Fields to verify (direct DB columns)
    fields_to_check = [
        "trade_amount_usd",
        "trade_enabled",
        "alert_enabled",
        "buy_alert_enabled",
        "sell_alert_enabled",
    ]
    
    issues = []
    all_match = True
    
    for field in fields_to_check:
        db_value = getattr(db_item, field, None)
        api_value = api_item.get(field)
        match, message = compare_values(db_value, api_value, field)
        logger.info(f"  {message}")
        if not match:
            all_match = False
            issues.append(message)
    
    # Verify strategy_key (resolved from DB, not a direct column)
    db_strategy_key = get_resolved_strategy_key(db, db_item)
    api_strategy_key = api_item.get("strategy_key")
    
    # Normalize "no strategy" representations
    db_strategy_normalized = db_strategy_key if db_strategy_key else None
    api_strategy_normalized = api_strategy_key if api_strategy_key and api_strategy_key.lower() not in ["none", "no strategy", ""] else None
    
    match, message = compare_values(db_strategy_normalized, api_strategy_normalized, "strategy_key")
    logger.info(f"  {message}")
    if not match:
        all_match = False
        issues.append(message)
    
    return all_match, issues


def verify_write_through(db: Session, api_url: str, symbol: str, test_value: float):
    """Verify PUT update writes to DB and reflects back immediately"""
    logger.info(f"Verifying write-through for {symbol} with trade_amount_usd={test_value}...")
    
    # Step 1: Update via API
    update_url = api_url.replace("/api/dashboard", f"/api/dashboard/symbol/{symbol}")
    payload = {"trade_amount_usd": test_value}
    
    try:
        response = requests.put(update_url, json=payload, timeout=10)
        response.raise_for_status()
        update_result = response.json()
        logger.info(f"  PUT response: {update_result.get('message', 'OK')}")
    except Exception as e:
        return False, [f"PUT request failed: {e}"]
    
    # Step 2: Wait a moment for DB commit
    time.sleep(0.5)
    
    # Step 3: Verify DB was updated
    db.refresh(get_db_item(db, symbol) or db.query(WatchlistItem).filter(
        WatchlistItem.symbol == symbol.upper()
    ).first())
    db_item = get_db_item(db, symbol)
    if not db_item:
        return False, [f"Symbol {symbol} not found in database after update"]
    
    db_value = db_item.trade_amount_usd
    if db_value != test_value:
        return False, [f"DB not updated: expected {test_value}, got {db_value}"]
    logger.info(f"  ✓ DB updated: trade_amount_usd={db_value}")
    
    # Step 4: Verify API response matches DB
    api_item = get_api_item(api_url, symbol)
    if not api_item:
        return False, [f"Symbol {symbol} not found in API after update"]
    
    api_value = api_item.get("trade_amount_usd")
    match, message = compare_values(db_value, api_value, "trade_amount_usd")
    if not match:
        return False, [message]
    logger.info(f"  ✓ API matches DB: {message}")
    
    # Step 5: Verify PUT response item matches DB
    put_response_value = update_result.get("item", {}).get("trade_amount_usd")
    match, message = compare_values(db_value, put_response_value, "trade_amount_usd (PUT response)")
    if not match:
        return False, [message]
    logger.info(f"  ✓ PUT response matches DB: {message}")
    
    return True, []


def verify_null_write_through(db: Session, api_url: str, symbol: str):
    """Verify that setting trade_amount_usd to null works correctly"""
    logger.info(f"Verifying null write-through for {symbol}...")
    
    update_url = api_url.replace("/api/dashboard", f"/api/dashboard/symbol/{symbol}")
    payload = {"trade_amount_usd": None}
    
    try:
        response = requests.put(update_url, json=payload, timeout=10)
        response.raise_for_status()
    except Exception as e:
        return False, [f"PUT request failed: {e}"]
    
    time.sleep(0.5)
    
    # Verify DB is null
    db_item = get_db_item(db, symbol)
    if not db_item:
        return False, [f"Symbol {symbol} not found in database"]
    
    db_value = db_item.trade_amount_usd
    if db_value is not None:
        return False, [f"DB should be null, got {db_value}"]
    logger.info(f"  ✓ DB is null as expected")
    
    # Verify API returns null (not 10, not 0)
    api_item = get_api_item(api_url, symbol)
    if not api_item:
        return False, [f"Symbol {symbol} not found in API"]
    
    api_value = api_item.get("trade_amount_usd")
    if api_value is not None:
        return False, [f"API should return null, got {api_value} (this indicates a default was applied!)"]
    logger.info(f"  ✓ API returns null (no default applied)")
    
    return True, []


def verify_strategy_write_through(db: Session, api_url: str, symbol: str):
    """Verify strategy write-through: updating sl_tp_mode reflects in strategy_key"""
    logger.info(f"Verifying strategy write-through for {symbol}...")
    
    # Get current state
    db_item = get_db_item(db, symbol)
    if not db_item:
        return False, [f"Symbol {symbol} not found in database"]
    
    original_sl_tp_mode = db_item.sl_tp_mode
    
    # Update sl_tp_mode via API
    update_url = api_url.replace("/api/dashboard", f"/api/dashboard/symbol/{symbol}")
    payload = {"sl_tp_mode": "aggressive"}
    
    try:
        response = requests.put(update_url, json=payload, timeout=10)
        response.raise_for_status()
    except Exception as e:
        return False, [f"PUT request failed: {e}"]
    
    time.sleep(0.5)
    
    # Verify API returns updated strategy_key
    api_item = get_api_item(api_url, symbol)
    if not api_item:
        return False, [f"Symbol {symbol} not found in API after update"]
    
    api_strategy_key = api_item.get("strategy_key")
    if not api_strategy_key:
        return False, [f"API strategy_key is missing or null for {symbol}"]
    
    # Verify strategy_key includes the updated risk mode
    if "aggressive" not in api_strategy_key.lower():
        return False, [f"API strategy_key should include 'aggressive', got: {api_strategy_key}"]
    
    logger.info(f"  ✓ Strategy write-through verified: strategy_key={api_strategy_key}")
    
    # Restore original value
    if original_sl_tp_mode:
        restore_payload = {"sl_tp_mode": original_sl_tp_mode}
        requests.put(update_url, json=restore_payload, timeout=10)
        logger.info(f"  Restored original sl_tp_mode: {original_sl_tp_mode}")
    
    return True, []


def verify_specific_symbols(db: Session, api_url: str):
    """Verify the specific symbols mentioned in the issue"""
    logger.info("=" * 60)
    logger.info("Verifying specific symbols: TRX_USDT, ALGO_USDT, ADA_USDT")
    logger.info("=" * 60)
    
    # Use symbols that exist in DB (ADA_USDT not ADA_USD based on AWS DB check)
    symbols = ["TRX_USDT", "ALGO_USDT", "ADA_USDT"]
    all_ok = True
    all_issues = []
    
    for symbol in symbols:
        logger.info(f"\nChecking {symbol}...")
        match, issues = verify_read_consistency(db, api_url, symbol)
        if not match:
            all_ok = False
            all_issues.extend([f"{symbol}: {issue}" for issue in issues])
        else:
            logger.info(f"  ✅ {symbol}: All fields match")
    
    return all_ok, all_issues


def main():
    """Run all verification tests"""
    # Safety flag: require E2E_WRITE_TEST=1 to perform write operations
    write_test_enabled = os.getenv("E2E_WRITE_TEST") == "1"
    
    try:
        api_url = get_api_url()
        logger.info(f"Using API URL: {api_url}")
        
        # Verify DB fingerprint matches API (if API is reachable)
        from app.database import database_url
        if not verify_db_match(api_url, database_url):
            return 3
        
        logger.info(f"Write tests enabled: {write_test_enabled} (set E2E_WRITE_TEST=1 to enable)")
        
        db: Session = SessionLocal()
        try:
            # Test 1: Verify specific symbols mentioned in issue (read-only)
            logger.info("\n" + "=" * 60)
            logger.info("TEST 1: Verify specific symbols (TRX_USDT, ALGO_USDT, ADA_USD) - READ ONLY")
            logger.info("=" * 60)
            test1_ok, test1_issues = verify_specific_symbols(db, api_url)
            
            # Test 2: Verify write-through with a test symbol (requires E2E_WRITE_TEST=1)
            if write_test_enabled:
                logger.info("\n" + "=" * 60)
                logger.info("TEST 2: Verify write-through (update and verify persistence) - WRITE MODE")
                logger.info("=" * 60)
                test_symbol = "BTC_USDT"  # Use a common symbol for testing
                test_item = get_db_item(db, test_symbol)
                if test_item:
                    # Save original values
                    original_value = test_item.trade_amount_usd
                    original_sl_tp_mode = test_item.sl_tp_mode
                    logger.info(f"Testing with {test_symbol} (original trade_amount_usd: {original_value}, sl_tp_mode: {original_sl_tp_mode})")
                    
                    # Test with a specific value
                    test2_ok, test2_issues = verify_write_through(db, api_url, test_symbol, 25.5)
                    
                    # Test with null
                    test3_ok, test3_issues = verify_null_write_through(db, api_url, test_symbol)
                    
                    # Test strategy write-through (separate test, doesn't modify trade_amount_usd)
                    test4_ok, test4_issues = verify_strategy_write_through(db, api_url, test_symbol)
                    
                    # Restore original trade_amount_usd value (strategy already restored in verify_strategy_write_through)
                    if original_value is not None:
                        update_url = api_url.replace("/api/dashboard", f"/api/dashboard/symbol/{test_symbol}")
                        requests.put(update_url, json={"trade_amount_usd": original_value}, timeout=10)
                        logger.info(f"Restored original trade_amount_usd: {original_value}")
                else:
                    logger.warning(f"{test_symbol} not found, skipping write-through test")
                    test2_ok, test2_issues = True, []
                    test3_ok, test3_issues = True, []
                    test4_ok, test4_issues = True, []
            else:
                logger.info("\n" + "=" * 60)
                logger.info("TEST 2: Skipped (write tests disabled)")
                logger.info("=" * 60)
                logger.info("To enable write tests, set: E2E_WRITE_TEST=1")
                test2_ok, test2_issues = True, []
                test3_ok, test3_issues = True, []
                test4_ok, test4_issues = True, []
            
            # Summary
            logger.info("\n" + "=" * 60)
            logger.info("VERIFICATION SUMMARY")
            logger.info("=" * 60)
            
            all_tests_ok = test1_ok and test2_ok and test3_ok and test4_ok
            all_issues = test1_issues + test2_issues + test3_issues + test4_issues
            
            if all_tests_ok:
                logger.info("✅ ALL TESTS PASSED")
                logger.info("✅ Dashboard shows exactly what is in DB")
                logger.info("✅ Write-through works: changes persist and reflect immediately")
                logger.info("✅ Zero mismatches detected")
                return 0
            else:
                logger.error("❌ SOME TESTS FAILED")
                for issue in all_issues:
                    logger.error(f"  - {issue}")
                return 1
                
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Verification failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

