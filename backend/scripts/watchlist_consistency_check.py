#!/usr/bin/env python3
"""
Watchlist Consistency Check Script

Compares dashboard API data (/api/dashboard) with backend database (WatchlistItem),
checking for inconsistencies between what the dashboard shows and what's in the database.
"""

import sys
import os
from pathlib import Path
from datetime import datetime
import requests
from typing import Dict, List, Optional, Any
import hashlib
from urllib.parse import urlparse, urlunparse

# Add parent directory to path to import app modules
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.signal_throttle import SignalThrottleState
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
            logger.error("Run via: backend/scripts/run_in_backend_container.sh python3 scripts/watchlist_consistency_check.py")
            logger.error("=" * 70)
            return False
        return True
    except requests.exceptions.RequestException:
        # API not reachable - skip verification but still honor host check
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


def normalize_symbol(symbol: str) -> str:
    """Normalize symbol to uppercase for comparison"""
    return symbol.upper() if symbol else ""


def get_api_watchlist_data(api_url: str = "http://localhost:8002/api/dashboard") -> Dict[str, Dict]:
    """Get watchlist data from the dashboard API"""
    try:
        logger.info(f"Fetching watchlist data from API: {api_url}")
        response = requests.get(api_url, timeout=30)
        response.raise_for_status()
        api_items = response.json()
        
        # Convert list to dict keyed by symbol for easy lookup
        api_data = {}
        for item in api_items:
            symbol = normalize_symbol(item.get("symbol", ""))
            if symbol:
                api_data[symbol] = item
        
        logger.info(f"Retrieved {len(api_data)} items from API")
        return api_data
    except requests.exceptions.RequestException as e:
        logger.warning(f"Could not fetch API data: {e}")
        return {}
    except Exception as e:
        logger.warning(f"Error parsing API response: {e}")
        return {}


def get_watchlist_items(db: Session) -> list:
    """Get all non-deleted watchlist items from database"""
    return db.query(WatchlistItem).filter(
        WatchlistItem.is_deleted == False
    ).all()


def get_throttle_states(db: Session) -> dict:
    """Get throttle states for all symbols/strategies"""
    throttle_states = {}
    try:
        # Query only columns that exist in the database
        # Use raw SQL to avoid schema mismatch issues (previous_price column may not exist)
        from sqlalchemy import text
        result = db.execute(text("""
            SELECT symbol, strategy_key, side 
            FROM signal_throttle_states
        """))
        for row in result:
            key = f"{row.symbol}_{row.strategy_key}_{row.side}"
            throttle_states[key] = {"symbol": row.symbol, "strategy_key": row.strategy_key, "side": row.side}
    except Exception as e:
        logger.warning(f"Could not fetch throttle states (schema may be outdated): {e}")
        # Return empty dict if query fails - this is non-critical for the consistency check
    return throttle_states


def compare_values(db_value: Any, api_value: Any, field_name: str) -> Optional[str]:
    """Compare two values and return a description of the difference if they differ"""
    # Handle None values
    if db_value is None and api_value is None:
        return None
    if db_value is None:
        return f"DB=None, API={api_value}"
    if api_value is None:
        return f"DB={db_value}, API=None"
    
    # Handle boolean values
    if isinstance(db_value, bool) and isinstance(api_value, bool):
        if db_value != api_value:
            return f"DB={db_value}, API={api_value}"
        return None
    
    # Handle numeric values (with small tolerance for floats)
    if isinstance(db_value, (int, float)) and isinstance(api_value, (int, float)):
        if isinstance(db_value, float) or isinstance(api_value, float):
            # Use relative tolerance for floats
            if abs(db_value - api_value) > max(1e-6, abs(db_value) * 0.001):
                return f"DB={db_value}, API={api_value}"
        else:
            if db_value != api_value:
                return f"DB={db_value}, API={api_value}"
        return None
    
    # Handle string values
    if str(db_value).strip() != str(api_value).strip():
        return f"DB={db_value}, API={api_value}"
    
    return None


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


def check_consistency(db: Session, api_url: str = "http://localhost:8002/api/dashboard") -> dict:
    """Check watchlist consistency between API and database, return report data"""
    # Verify DB fingerprint matches API (if API is reachable)
    from app.database import database_url
    if not verify_db_match(api_url, database_url):
        raise SystemExit(3)
    
    # Get data from both sources
    watchlist_items = get_watchlist_items(db)
    api_data = get_api_watchlist_data(api_url)
    
    try:
        throttle_states = get_throttle_states(db)
    except Exception as e:
        logger.warning(f"Could not fetch throttle states, continuing without them: {e}")
        throttle_states = {}
    
    # Fields to compare between API and DB
    fields_to_compare = [
        "trade_enabled",
        "alert_enabled",
        "buy_alert_enabled",
        "sell_alert_enabled",
        "trade_amount_usd",
        "sl_tp_mode",
    ]
    
    report_data = {
        "timestamp": datetime.now().isoformat(),
        "total_items": len(watchlist_items),
        "items": [],
        "issues": [],
        "api_available": len(api_data) > 0,
        "summary": {
            "total": len(watchlist_items),
            "trade_enabled": 0,
            "alert_enabled": 0,
            "buy_alert_enabled": 0,
            "sell_alert_enabled": 0,
            "with_throttle_state": 0,
            "api_mismatches": 0,
            "only_in_db": 0,
            "only_in_api": 0,
        }
    }
    
    # Track symbols we've seen
    symbols_in_api = set()
    
    for item in watchlist_items:
        symbol = normalize_symbol(item.symbol)
        
        # Count enabled flags from DB
        if item.trade_enabled:
            report_data["summary"]["trade_enabled"] += 1
        if item.alert_enabled:
            report_data["summary"]["alert_enabled"] += 1
        if item.buy_alert_enabled:
            report_data["summary"]["buy_alert_enabled"] += 1
        if item.sell_alert_enabled:
            report_data["summary"]["sell_alert_enabled"] += 1
        
        # Check for throttle state
        has_throttle = False
        for key in throttle_states.keys():
            if key.startswith(f"{symbol}_"):
                has_throttle = True
                report_data["summary"]["with_throttle_state"] += 1
                break
        
        # Check for inconsistencies between DB and API
        issues = []
        api_item = api_data.get(symbol)
        
        if api_item:
            symbols_in_api.add(symbol)
            # Compare fields
            mismatches = []
            for field in fields_to_compare:
                db_value = getattr(item, field, None)
                api_value = api_item.get(field)
                diff = compare_values(db_value, api_value, field)
                if diff:
                    mismatches.append(f"{field}: {diff}")
            
            # CRITICAL: Compare resolved strategy (preset-risk) between DB and API
            # This ensures dropdown and tooltip match
            db_strategy_key = get_resolved_strategy_key(db, item)
            api_strategy_key = api_item.get("strategy_key")
            
            # Normalize "no strategy" representations
            db_strategy_normalized = db_strategy_key if db_strategy_key else None
            api_strategy_normalized = api_strategy_key if api_strategy_key and api_strategy_key.lower() not in ["none", "no strategy", ""] else None
            
            if db_strategy_normalized != api_strategy_normalized:
                db_display = db_strategy_key if db_strategy_key else "None"
                api_display = api_strategy_key if api_strategy_key else "None"
                mismatches.append(f"strategy: DB={db_display}, API={api_display}")
            
            if mismatches:
                issues.extend(mismatches)
                report_data["summary"]["api_mismatches"] += 1
        else:
            # Symbol exists in DB but not in API
            issues.append("Symbol exists in DB but not in API response")
            report_data["summary"]["only_in_db"] += 1
        
        # Check for internal consistency (alert flags logic)
        if item.alert_enabled and not (item.buy_alert_enabled or item.sell_alert_enabled):
            issues.append("alert_enabled=True but both buy/sell alerts are False")
        
        if (item.buy_alert_enabled or item.sell_alert_enabled) and not item.alert_enabled:
            issues.append("buy/sell alert enabled but master alert_enabled=False")
        
        # Get resolved strategy for display
        db_strategy_key = get_resolved_strategy_key(db, item)
        api_strategy_key = api_item.get("strategy_key") if api_item else None
        
        item_data = {
            "symbol": symbol,
            "trade_enabled": item.trade_enabled,
            "alert_enabled": item.alert_enabled,
            "buy_alert_enabled": item.buy_alert_enabled,
            "sell_alert_enabled": item.sell_alert_enabled,
            "has_throttle_state": has_throttle,
            "in_api": api_item is not None,
            "strategy_db": db_strategy_key or "None",
            "strategy_api": api_strategy_key or "None",
            "issues": issues
        }
        
        report_data["items"].append(item_data)
        
        if issues:
            report_data["issues"].extend([
                {"symbol": symbol, "issue": issue} for issue in issues
            ])
    
    # Check for symbols in API but not in DB
    db_symbols = {normalize_symbol(item.symbol) for item in watchlist_items}
    for api_symbol in api_data.keys():
        if api_symbol not in db_symbols:
            report_data["summary"]["only_in_api"] += 1
            report_data["issues"].append({
                "symbol": api_symbol,
                "issue": "Symbol exists in API but not in DB"
            })
    
    return report_data


def generate_markdown_report(report_data: dict) -> str:
    """Generate markdown report from report data"""
    lines = []
    lines.append("# Watchlist Consistency Report")
    lines.append("")
    lines.append(f"**Generated:** {report_data['timestamp']}")
    lines.append("")
    lines.append("**Purpose:** Compares dashboard API data (`/api/dashboard`) with backend database (`WatchlistItem`)")
    lines.append("")
    
    # Summary
    summary = report_data["summary"]
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total Items (DB):** {summary['total']}")
    lines.append(f"- **API Available:** {'✅ Yes' if report_data.get('api_available', False) else '❌ No'}")
    lines.append(f"- **Trade Enabled (DB):** {summary['trade_enabled']}")
    lines.append(f"- **Alert Enabled (Master, DB):** {summary['alert_enabled']}")
    lines.append(f"- **Buy Alert Enabled (DB):** {summary['buy_alert_enabled']}")
    lines.append(f"- **Sell Alert Enabled (DB):** {summary['sell_alert_enabled']}")
    lines.append(f"- **With Throttle State:** {summary['with_throttle_state']}")
    lines.append("")
    lines.append("### API vs Database Comparison")
    lines.append("")
    lines.append(f"- **API Mismatches:** {summary.get('api_mismatches', 0)}")
    lines.append(f"- **Only in DB:** {summary.get('only_in_db', 0)}")
    lines.append(f"- **Only in API:** {summary.get('only_in_api', 0)}")
    lines.append("")
    
    # Issues
    if report_data["issues"]:
        lines.append("## ⚠️ Issues Found")
        lines.append("")
        for issue in report_data["issues"]:
            lines.append(f"- **{issue['symbol']}**: {issue['issue']}")
        lines.append("")
    else:
        lines.append("## ✅ No Issues Found")
        lines.append("")
        lines.append("All watchlist items are consistent between API and database.")
        lines.append("")
    
    # Detailed Items Table
    lines.append("## Watchlist Items")
    lines.append("")
    lines.append("| Symbol | Trade | Alert | Buy Alert | Sell Alert | Strategy (DB) | Strategy (API) | Throttle | In API | Issues |")
    lines.append("|--------|-------|-------|-----------|------------|---------------|---------------|----------|--------|--------|")
    
    for item in report_data["items"]:
        trade = "✅" if item["trade_enabled"] else "❌"
        alert = "✅" if item["alert_enabled"] else "❌"
        buy_alert = "✅" if item["buy_alert_enabled"] else "❌"
        sell_alert = "✅" if item["sell_alert_enabled"] else "❌"
        throttle = "✅" if item["has_throttle_state"] else "—"
        in_api = "✅" if item.get("in_api", False) else "❌"
        strategy_db = item.get("strategy_db", "—")
        strategy_api = item.get("strategy_api", "—")
        # Highlight strategy mismatches
        if strategy_db != strategy_api and strategy_db != "—" and strategy_api != "—":
            strategy_db = f"⚠️ {strategy_db}"
            strategy_api = f"⚠️ {strategy_api}"
        issues_str = "; ".join(item["issues"]) if item["issues"] else "—"
        
        lines.append(f"| {item['symbol']} | {trade} | {alert} | {buy_alert} | {sell_alert} | {strategy_db} | {strategy_api} | {throttle} | {in_api} | {issues_str} |")
    
    return "\n".join(lines)


def main():
    """Main function"""
    try:
        db: Session = SessionLocal()
        try:
            logger.info("Starting watchlist consistency check...")
            
            # Try to determine API URL from environment or use default
            # In Docker, try localhost:8002 first, then fallback to 8000
            api_url = os.getenv("API_URL")
            if not api_url:
                # Try common ports when running inside Docker
                for port in [8002, 8000]:
                    test_url = f"http://localhost:{port}/api/dashboard"
                    try:
                        response = requests.get(test_url, timeout=2)
                        if response.status_code == 200:
                            api_url = test_url
                            logger.info(f"Auto-detected API URL: {api_url}")
                            break
                    except:
                        continue
                
                if not api_url:
                    api_url = "http://localhost:8002/api/dashboard"
                    logger.warning(f"Could not auto-detect API URL, using default: {api_url}")
            
            logger.info(f"Using API URL: {api_url}")
            
            # Run consistency check
            report_data = check_consistency(db, api_url=api_url)
            
            # Generate markdown report
            markdown_content = generate_markdown_report(report_data)
            
            # Determine report paths using same logic as routes_monitoring.py
            # Script is in backend/scripts/, so backend root is scripts/../
            script_dir = Path(__file__).parent
            backend_root = script_dir.parent.resolve()
            
            # Resolve project root: check if backend_root/docs exists, otherwise go up one level
            # This handles both Docker (/app) and local dev (backend/) cases
            if (backend_root / "docs").exists():
                project_root = backend_root
            else:
                # Go up one level (backend/ -> project_root/)
                project_root = backend_root.parent
            
            # If project_root is still "/", fall back to backend_root/docs
            if str(project_root) == "/" or not (project_root / "docs").exists():
                docs_dir = backend_root / "docs" / "monitoring"
            else:
                docs_dir = project_root / "docs" / "monitoring"
            
            # Ensure directory exists (create if needed)
            try:
                docs_dir.mkdir(parents=True, exist_ok=True)
            except PermissionError as pe:
                # If we can't write to docs, try /tmp as fallback
                logger.warning(f"Cannot write to {docs_dir}: {pe}. Using /tmp as fallback.")
                docs_dir = Path("/tmp") / "watchlist_consistency_reports"
                docs_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Using fallback directory: {docs_dir}")
            
            # Write latest report
            latest_report_path = docs_dir / "watchlist_consistency_report_latest.md"
            with open(latest_report_path, 'w') as f:
                f.write(markdown_content)
            logger.info(f"Report written to {latest_report_path}")
            
            # Write dated report
            date_str = datetime.now().strftime("%Y%m%d")
            dated_report_path = docs_dir / f"watchlist_consistency_report_{date_str}.md"
            with open(dated_report_path, 'w') as f:
                f.write(markdown_content)
            logger.info(f"Report written to {dated_report_path}")
            
            # Print summary
            issue_count = len(report_data["issues"])
            if issue_count > 0:
                logger.warning(f"Found {issue_count} issues")
                print(f"\n⚠️  Found {issue_count} consistency issues")
            else:
                logger.info("No issues found - watchlist is consistent")
                print("\n✅ No issues found - watchlist is consistent")
            
            print(f"\n📊 Summary:")
            print(f"  - Total items (DB): {report_data['summary']['total']}")
            print(f"  - API available: {'Yes' if report_data.get('api_available', False) else 'No'}")
            print(f"  - Trade enabled: {report_data['summary']['trade_enabled']}")
            print(f"  - Alert enabled: {report_data['summary']['alert_enabled']}")
            print(f"  - API mismatches: {report_data['summary'].get('api_mismatches', 0)}")
            print(f"  - Only in DB: {report_data['summary'].get('only_in_db', 0)}")
            print(f"  - Only in API: {report_data['summary'].get('only_in_api', 0)}")
            
            return 0 if issue_count == 0 else 1
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error running consistency check: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

