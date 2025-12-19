#!/usr/bin/env python3
"""
Watchlist Consistency Check Script

Compares backend watchlist data with expected state, checking for inconsistencies
in throttle flags, alert flags, and data integrity.
"""

import sys
import os
from pathlib import Path
from datetime import datetime

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


def normalize_symbol(symbol: str) -> str:
    """Normalize symbol to uppercase for comparison"""
    return symbol.upper() if symbol else ""


def get_watchlist_items(db: Session) -> list:
    """Get all non-deleted watchlist items"""
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


def check_consistency(db: Session) -> dict:
    """Check watchlist consistency and return report data"""
    watchlist_items = get_watchlist_items(db)
    try:
        throttle_states = get_throttle_states(db)
    except Exception as e:
        logger.warning(f"Could not fetch throttle states, continuing without them: {e}")
        throttle_states = {}
    
    report_data = {
        "timestamp": datetime.now().isoformat(),
        "total_items": len(watchlist_items),
        "items": [],
        "issues": [],
        "summary": {
            "total": len(watchlist_items),
            "trade_enabled": 0,
            "alert_enabled": 0,
            "buy_alert_enabled": 0,
            "sell_alert_enabled": 0,
            "with_throttle_state": 0,
        }
    }
    
    for item in watchlist_items:
        symbol = normalize_symbol(item.symbol)
        
        # Count enabled flags
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
        
        # Check for inconsistencies
        issues = []
        
        # Alert enabled should be consistent with buy/sell alerts
        if item.alert_enabled and not (item.buy_alert_enabled or item.sell_alert_enabled):
            issues.append("alert_enabled=True but both buy/sell alerts are False")
        
        # If buy or sell alert is enabled, master alert should be enabled
        if (item.buy_alert_enabled or item.sell_alert_enabled) and not item.alert_enabled:
            issues.append("buy/sell alert enabled but master alert_enabled=False")
        
        item_data = {
            "symbol": symbol,
            "trade_enabled": item.trade_enabled,
            "alert_enabled": item.alert_enabled,
            "buy_alert_enabled": item.buy_alert_enabled,
            "sell_alert_enabled": item.sell_alert_enabled,
            "has_throttle_state": has_throttle,
            "issues": issues
        }
        
        report_data["items"].append(item_data)
        
        if issues:
            report_data["issues"].extend([
                {"symbol": symbol, "issue": issue} for issue in issues
            ])
    
    return report_data


def generate_markdown_report(report_data: dict) -> str:
    """Generate markdown report from report data"""
    lines = []
    lines.append("# Watchlist Consistency Report")
    lines.append("")
    lines.append(f"**Generated:** {report_data['timestamp']}")
    lines.append("")
    
    # Summary
    summary = report_data["summary"]
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total Items:** {summary['total']}")
    lines.append(f"- **Trade Enabled:** {summary['trade_enabled']}")
    lines.append(f"- **Alert Enabled (Master):** {summary['alert_enabled']}")
    lines.append(f"- **Buy Alert Enabled:** {summary['buy_alert_enabled']}")
    lines.append(f"- **Sell Alert Enabled:** {summary['sell_alert_enabled']}")
    lines.append(f"- **With Throttle State:** {summary['with_throttle_state']}")
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
        lines.append("All watchlist items are consistent.")
        lines.append("")
    
    # Detailed Items Table
    lines.append("## Watchlist Items")
    lines.append("")
    lines.append("| Symbol | Trade | Alert | Buy Alert | Sell Alert | Throttle | Issues |")
    lines.append("|--------|-------|-------|-----------|------------|----------|--------|")
    
    for item in report_data["items"]:
        trade = "✅" if item["trade_enabled"] else "❌"
        alert = "✅" if item["alert_enabled"] else "❌"
        buy_alert = "✅" if item["buy_alert_enabled"] else "❌"
        sell_alert = "✅" if item["sell_alert_enabled"] else "❌"
        throttle = "✅" if item["has_throttle_state"] else "—"
        issues_str = "; ".join(item["issues"]) if item["issues"] else "—"
        
        lines.append(f"| {item['symbol']} | {trade} | {alert} | {buy_alert} | {sell_alert} | {throttle} | {issues_str} |")
    
    return "\n".join(lines)


def main():
    """Main function"""
    try:
        db: Session = SessionLocal()
        try:
            logger.info("Starting watchlist consistency check...")
            
            # Run consistency check
            report_data = check_consistency(db)
            
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
            print(f"  - Total items: {report_data['summary']['total']}")
            print(f"  - Trade enabled: {report_data['summary']['trade_enabled']}")
            print(f"  - Alert enabled: {report_data['summary']['alert_enabled']}")
            
            return 0 if issue_count == 0 else 1
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error running consistency check: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

