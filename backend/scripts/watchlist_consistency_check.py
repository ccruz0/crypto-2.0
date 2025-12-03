#!/usr/bin/env python3
"""
Daily watchlist consistency check.

This script compares watchlist values across three layers:
1. API/UI layer: JSON returned by /api/watchlist (what the frontend shows)
2. Database layer: WatchlistItem records in the database
3. Strategy/calculation layer: Ground truth values computed using the same functions as the live monitor

It generates a daily Markdown report showing which symbols are consistent and which have mismatches.

Usage:
    python scripts/watchlist_consistency_check.py
    OR
    docker compose exec -T backend-aws python scripts/watchlist_consistency_check.py
"""
import sys
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Literal
import json
import requests
import logging

# Add backend directory to path for imports
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.services.signal_evaluator import evaluate_signal_for_symbol
from app.services.watchlist_selector import get_canonical_watchlist_item

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Tolerance for numeric comparisons
REL_TOL = 0.001  # 0.1%
ABS_TOL = 1e-6

# Fields to compare
NUMERIC_FIELDS = [
    "price", "rsi", "ma50", "ma200", "ema10", "atr",
    "buy_target", "take_profit", "stop_loss",
    "sl_price", "tp_price", "sl_percentage", "tp_percentage",
    "min_price_change_pct", "alert_cooldown_minutes", "trade_amount_usd"
]

BOOLEAN_FIELDS = [
    "alert_enabled", "buy_alert_enabled", "sell_alert_enabled",
    "trade_enabled", "trade_on_margin", "sold", "is_deleted",
    "skip_sl_tp_reminder"
]

STRING_FIELDS = [
    "sl_tp_mode", "order_status", "exchange"
]


def classify_numeric_match(a: Optional[float], b: Optional[float], c: Optional[float] = None) -> Literal["EXACT_MATCH", "NUMERIC_DRIFT", "MISMATCH"]:
    """
    Classify numeric comparison between values.
    
    Args:
        a: First value (DB)
        b: Second value (API)
        c: Third value (Computed), optional
        
    Returns:
        Classification: EXACT_MATCH, NUMERIC_DRIFT, or MISMATCH
    """
    # If all are None, it's a match
    if a is None and b is None and (c is None or c is None):
        return "EXACT_MATCH"
    
    # If only one is None, it's a mismatch
    if (a is None) != (b is None):
        return "MISMATCH"
    if c is not None and (a is None) != (c is None):
        return "MISMATCH"
    
    # If all are None, already handled above
    if a is None:
        return "EXACT_MATCH"
    
    # Compare a and b
    diff_ab = abs(a - b)
    max_ab = max(abs(a), abs(b))
    
    if diff_ab <= max(ABS_TOL, REL_TOL * max_ab):
        match_ab = True
    else:
        match_ab = False
    
    # Compare with computed value if provided
    if c is not None:
        diff_ac = abs(a - c)
        max_ac = max(abs(a), abs(c))
        
        if diff_ac <= max(ABS_TOL, REL_TOL * max_ac):
            match_ac = True
        else:
            match_ac = False
        
        # All three must match for EXACT_MATCH
        if match_ab and match_ac:
            return "EXACT_MATCH"
        elif match_ab or match_ac:
            return "NUMERIC_DRIFT"
        else:
            return "MISMATCH"
    else:
        # Only comparing a and b
        if match_ab:
            return "EXACT_MATCH"
        else:
            return "NUMERIC_DRIFT" if diff_ab <= max(ABS_TOL * 10, REL_TOL * 10 * max_ab) else "MISMATCH"


def classify_boolean_match(a: Optional[bool], b: Optional[bool], c: Optional[bool] = None) -> Literal["EXACT_MATCH", "MISMATCH"]:
    """Classify boolean comparison."""
    # Normalize None to False for comparison
    a_norm = bool(a) if a is not None else False
    b_norm = bool(b) if b is not None else False
    c_norm = bool(c) if c is not None else False
    
    if c is not None:
        if a_norm == b_norm == c_norm:
            return "EXACT_MATCH"
        else:
            return "MISMATCH"
    else:
        return "EXACT_MATCH" if a_norm == b_norm else "MISMATCH"


def classify_string_match(a: Optional[str], b: Optional[str], c: Optional[str] = None) -> Literal["EXACT_MATCH", "MISMATCH"]:
    """Classify string comparison."""
    a_norm = (a or "").strip().upper()
    b_norm = (b or "").strip().upper()
    
    if c is not None:
        c_norm = (c or "").strip().upper()
        if a_norm == b_norm == c_norm:
            return "EXACT_MATCH"
        else:
            return "MISMATCH"
    else:
        return "EXACT_MATCH" if a_norm == b_norm else "MISMATCH"


def fetch_api_watchlist() -> Dict[str, Dict[str, Any]]:
    """
    Fetch watchlist from API endpoint.
    
    Returns:
        Dict mapping symbol -> watchlist item data
    """
    try:
        # Try to call the API from inside the container
        # The API should be available at localhost:8000 or 8002
        # Try /api/dashboard first (from routes_dashboard), then /api/watchlist
        endpoints = [
            ("http://localhost:8000/api/dashboard", 8000),
            ("http://localhost:8002/api/dashboard", 8002),
            ("http://localhost:8000/api/watchlist", 8000),
            ("http://localhost:8002/api/watchlist", 8002),
        ]
        
        for url, port in endpoints:
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    items = response.json()
                    # Handle both list and dict responses
                    if isinstance(items, dict):
                        # If it's a dict, try to extract a list from common keys
                        items = items.get("data", items.get("watchlist", items.get("items", [])))
                    
                    if not isinstance(items, list):
                        continue
                    
                    # Convert list to dict keyed by symbol
                    result = {}
                    for item in items:
                        symbol = item.get("symbol", "").upper()
                        if symbol:
                            result[symbol] = item
                    logger.info(f"Fetched {len(result)} items from API ({url})")
                    return result
            except Exception as e:
                logger.debug(f"Failed to fetch from {url}: {e}")
                continue
        
        logger.warning("Could not fetch from API, returning empty dict")
        return {}
    except Exception as e:
        logger.error(f"Error fetching API watchlist: {e}")
        return {}


def get_db_watchlist_item(db: Session, symbol: str) -> Optional[WatchlistItem]:
    """Get watchlist item from database."""
    try:
        item = get_canonical_watchlist_item(db, symbol)
        return item
    except Exception as e:
        logger.warning(f"Error fetching DB item for {symbol}: {e}")
        return None


def get_computed_values(db: Session, watchlist_item: WatchlistItem) -> Dict[str, Any]:
    """
    Get computed/ground truth values using the same evaluation logic as the live monitor.
    
    Returns:
        Dict with computed values (price, rsi, ma50, ma200, ema10, etc.)
    """
    try:
        result = evaluate_signal_for_symbol(db, watchlist_item, watchlist_item.symbol)
        
        computed = {
            "price": result.get("price"),
            "rsi": result.get("rsi"),
            "ma50": result.get("ma50"),
            "ma200": result.get("ma200"),
            "ema10": result.get("ema10"),
            "volume_ratio": result.get("volume_ratio"),
            "min_volume_ratio": result.get("min_volume_ratio"),
            "decision": result.get("decision"),
            "buy_signal": result.get("buy_signal"),
            "sell_signal": result.get("sell_signal"),
            "index": result.get("index"),
            "strategy_key": result.get("strategy_key"),
            "preset": result.get("preset"),
        }
        
        # Add error if present
        if result.get("error"):
            computed["error"] = result.get("error")
        
        return computed
    except Exception as e:
        logger.warning(f"Error computing values for {watchlist_item.symbol}: {e}")
        return {"error": str(e)}


def compare_field(
    field_name: str,
    db_value: Any,
    api_value: Any,
    computed_value: Any = None
) -> Dict[str, Any]:
    """
    Compare a single field across three layers.
    
    Returns:
        Dict with comparison result
    """
    if field_name in NUMERIC_FIELDS:
        classification = classify_numeric_match(db_value, api_value, computed_value)
    elif field_name in BOOLEAN_FIELDS:
        classification = classify_boolean_match(db_value, api_value, computed_value)
    elif field_name in STRING_FIELDS:
        classification = classify_string_match(db_value, api_value, computed_value)
    else:
        # Default: exact match for unknown types
        if db_value == api_value == (computed_value if computed_value is not None else db_value):
            classification = "EXACT_MATCH"
        else:
            classification = "MISMATCH"
    
    return {
        "name": field_name,
        "db": db_value,
        "api": api_value,
        "computed": computed_value,
        "classification": classification
    }


def compare_symbol(
    db: Session,
    symbol: str,
    api_items: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Compare a single symbol across all three layers.
    
    Returns:
        Dict with comparison results for the symbol
    """
    # Get DB item
    db_item = get_db_watchlist_item(db, symbol)
    if not db_item:
        return {
            "symbol": symbol,
            "status": "ERROR",
            "error": "Not found in database",
            "fields": []
        }
    
    # Get API item
    api_item = api_items.get(symbol.upper(), {})
    
    # Get computed values
    computed = get_computed_values(db, db_item)
    
    # Compare all fields
    fields = []
    
    # Numeric fields
    for field in NUMERIC_FIELDS:
        try:
            db_val = getattr(db_item, field, None)
            api_val = api_item.get(field) if api_item else None
            computed_val = computed.get(field) if computed else None
            fields.append(compare_field(field, db_val, api_val, computed_val))
        except Exception as e:
            logger.debug(f"Error comparing field {field} for {symbol}: {e}")
            fields.append({
                "name": field,
                "db": None,
                "api": None,
                "computed": None,
                "classification": "MISMATCH",
                "error": str(e)
            })
    
    # Boolean fields
    for field in BOOLEAN_FIELDS:
        try:
            db_val = getattr(db_item, field, None)
            api_val = api_item.get(field) if api_item else None
            # Computed values don't have these flags, so skip computed for booleans
            fields.append(compare_field(field, db_val, api_val, None))
        except Exception as e:
            logger.debug(f"Error comparing field {field} for {symbol}: {e}")
            fields.append({
                "name": field,
                "db": None,
                "api": None,
                "computed": None,
                "classification": "MISMATCH",
                "error": str(e)
            })
    
    # String fields
    for field in STRING_FIELDS:
        try:
            db_val = getattr(db_item, field, None)
            api_val = api_item.get(field) if api_item else None
            fields.append(compare_field(field, db_val, api_val, None))
        except Exception as e:
            logger.debug(f"Error comparing field {field} for {symbol}: {e}")
            fields.append({
                "name": field,
                "db": None,
                "api": None,
                "computed": None,
                "classification": "MISMATCH",
                "error": str(e)
            })
    
    # Determine overall status
    has_mismatch = any(f["classification"] == "MISMATCH" for f in fields)
    has_drift = any(f["classification"] == "NUMERIC_DRIFT" for f in fields)
    
    if has_mismatch:
        status = "HAS_ISSUES"
    elif has_drift:
        status = "MINOR_DRIFT"
    else:
        status = "OK"
    
    return {
        "symbol": symbol,
        "status": status,
        "fields": fields,
        "computed": computed
    }


def generate_report(results: Dict[str, Any], output_dir: str = "docs/monitoring") -> str:
    """
    Generate Markdown report from comparison results.
    
    Returns:
        Path to generated report file
    """
    os.makedirs(output_dir, exist_ok=True)
    
    run_timestamp = results["run_timestamp"]
    date_str = run_timestamp[:10].replace("-", "")
    
    filename = f"watchlist_consistency_report_{date_str}.md"
    filepath = os.path.join(output_dir, filename)
    latest_filepath = os.path.join(output_dir, "watchlist_consistency_report_latest.md")
    
    with open(filepath, "w") as f:
        f.write(f"# Watchlist Consistency Report\n\n")
        f.write(f"**Generated:** {run_timestamp}\n\n")
        
        summary = results["summary"]
        f.write(f"## Summary\n\n")
        f.write(f"- **Total Symbols:** {summary['total_symbols']}\n")
        f.write(f"- **All OK:** {summary['symbols_all_ok']}\n")
        f.write(f"- **Minor Drift:** {summary['symbols_with_drift']}\n")
        f.write(f"- **Has Issues:** {summary['symbols_with_issues']}\n\n")
        
        # Symbols with issues table
        if summary['symbols_with_issues'] > 0:
            f.write(f"## Symbols with Issues\n\n")
            f.write(f"| Symbol | Status | Issues |\n")
            f.write(f"|--------|--------|--------|\n")
            
            for symbol_data in results["symbols"]:
                if symbol_data["status"] == "HAS_ISSUES":
                    mismatches = [f["name"] for f in symbol_data["fields"] if f["classification"] == "MISMATCH"]
                    issues_str = ", ".join(mismatches[:5])  # Limit to 5 for table
                    if len(mismatches) > 5:
                        issues_str += f" (+{len(mismatches) - 5} more)"
                    f.write(f"| {symbol_data['symbol']} | {symbol_data['status']} | {issues_str} |\n")
            
            f.write(f"\n")
        
        # Detailed per-symbol section
        f.write(f"## Detailed Results\n\n")
        
        for symbol_data in results["symbols"]:
            symbol = symbol_data["symbol"]
            status = symbol_data["status"]
            
            f.write(f"### {symbol}\n\n")
            f.write(f"**Status:** {status}\n\n")
            
            if symbol_data.get("error"):
                f.write(f"**Error:** {symbol_data['error']}\n\n")
                continue
            
            # Field comparison table
            f.write(f"| Field | DB | API | Computed | Classification |\n")
            f.write(f"|-------|----|-----|----------|----------------|\n")
            
            for field in symbol_data["fields"]:
                db_val = field.get("db")
                api_val = field.get("api")
                computed_val = field.get("computed")
                classification = field.get("classification", "MISMATCH")
                error = field.get("error")
                
                # Format values for display
                def fmt_val(v):
                    if v is None:
                        return "None"
                    if isinstance(v, bool):
                        return "True" if v else "False"
                    if isinstance(v, float):
                        return f"{v:.6f}" if abs(v) < 1 else f"{v:.4f}"
                    return str(v)
                
                classification_str = classification
                if error:
                    classification_str = f"{classification} (error: {error})"
                
                f.write(f"| {field['name']} | {fmt_val(db_val)} | {fmt_val(api_val)} | {fmt_val(computed_val)} | {classification_str} |\n")
            
            # Add computed strategy info if available
            if symbol_data.get("computed") and not symbol_data["computed"].get("error"):
                computed = symbol_data["computed"]
                f.write(f"\n**Computed Strategy Info:**\n")
                f.write(f"- Preset: {computed.get('preset', 'N/A')}\n")
                f.write(f"- Strategy Key: {computed.get('strategy_key', 'N/A')}\n")
                f.write(f"- Decision: {computed.get('decision', 'N/A')}\n")
                f.write(f"- Index: {computed.get('index', 'N/A')}\n")
                f.write(f"- Buy Signal: {computed.get('buy_signal', False)}\n")
                f.write(f"- Sell Signal: {computed.get('sell_signal', False)}\n")
            
            f.write(f"\n")
    
    # Also write to latest
    import shutil
    shutil.copy(filepath, latest_filepath)
    
    logger.info(f"Report generated: {filepath}")
    return filepath


def main():
    """Main entry point."""
    # Telegram health-check at start of nightly consistency workflow
    try:
        from app.services.telegram_health import check_telegram_health
        health = check_telegram_health(origin="nightly_consistency")
        logger.info(f"[NIGHTLY_CONSISTENCY] Telegram health summary: enabled={health['enabled']}, "
                   f"token_present={health['token_present']}, chat_id_present={health['chat_id_present']}, "
                   f"fully_configured={health['fully_configured']}")
    except Exception as e:
        logger.warning(f"[NIGHTLY_CONSISTENCY] Failed to run Telegram health-check: {e}")
    
    run_timestamp = datetime.now(timezone.utc).isoformat()
    logger.info(f"[WATCHLIST_CONSISTENCY] Starting consistency check at {run_timestamp}")
    
    db = SessionLocal()
    try:
        # Fetch all watchlist items from DB
        watchlist_items = (
            db.query(WatchlistItem)
            .filter(WatchlistItem.is_deleted == False)
            .all()
        )
        
        logger.info(f"Found {len(watchlist_items)} watchlist items in database")
        
        # Fetch API watchlist
        api_items = fetch_api_watchlist()
        logger.info(f"Fetched {len(api_items)} items from API")
        
        # Compare each symbol
        results_list = []
        for item in watchlist_items:
            symbol = item.symbol.upper()
            logger.debug(f"Comparing {symbol}...")
            result = compare_symbol(db, symbol, api_items)
            results_list.append(result)
        
        # Build summary
        symbols_all_ok = sum(1 for r in results_list if r["status"] == "OK")
        symbols_with_drift = sum(1 for r in results_list if r["status"] == "MINOR_DRIFT")
        symbols_with_issues = sum(1 for r in results_list if r["status"] == "HAS_ISSUES")
        
        # Count fields with mismatches
        fields_with_mismatches = {}
        for result in results_list:
            for field in result.get("fields", []):
                if field["classification"] == "MISMATCH":
                    field_name = field["name"]
                    fields_with_mismatches[field_name] = fields_with_mismatches.get(field_name, 0) + 1
        
        results = {
            "run_timestamp": run_timestamp,
            "summary": {
                "total_symbols": len(results_list),
                "symbols_all_ok": symbols_all_ok,
                "symbols_with_drift": symbols_with_drift,
                "symbols_with_issues": symbols_with_issues,
                "fields_with_mismatches": fields_with_mismatches
            },
            "symbols": results_list
        }
        
        # Generate report
        report_path = generate_report(results)
        
        # Log summary
        logger.info(
            f"[WATCHLIST_CONSISTENCY] {run_timestamp} | "
            f"total={len(results_list)} | "
            f"all_ok={symbols_all_ok} | "
            f"drift={symbols_with_drift} | "
            f"issues={symbols_with_issues} | "
            f"report={report_path}"
        )
        
        # Optional: Send Telegram summary if there are issues
        if symbols_with_issues > 0:
            try:
                from app.services.telegram_notifier import send_message
                from app.core.runtime import get_runtime_origin
                
                date_str = run_timestamp[:10].replace("-", "")
                message = (
                    f"🔍 Watchlist consistency check done\n"
                    f"Total symbols: {len(results_list)}\n"
                    f"All OK: {symbols_all_ok}\n"
                    f"Minor drift: {symbols_with_drift}\n"
                    f"⚠️ Issues: {symbols_with_issues}\n"
                    f"Report: watchlist_consistency_report_{date_str}.md"
                )
                
                origin = get_runtime_origin()
                send_message(message, origin=origin)
                logger.info("Telegram summary sent")
            except Exception as e:
                logger.debug(f"Could not send Telegram summary: {e}")
        
        print(f"✅ Consistency check complete. Report: {report_path}")
        
    except Exception as e:
        logger.error(f"Error in consistency check: {e}", exc_info=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

