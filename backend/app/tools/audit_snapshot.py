#!/usr/bin/env python3
"""
Audit Snapshot Tool
Provides a quick health check of the trading platform
Can be run locally or on AWS
"""
import sys
import os
import time
import json
from typing import Dict, Any

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.models.watchlist import WatchlistItem
from app.services.watchlist_selector import deduplicate_watchlist_items
from app.utils.http_client import http_get

def get_api_url() -> str:
    """Get API base URL from environment"""
    return os.getenv("API_BASE_URL") or os.getenv("AWS_BACKEND_URL") or "http://localhost:8002"

def check_service_health(service: str, url: str) -> bool:
    """Check if a service is healthy"""
    try:
        response = http_get(url, timeout=5, calling_module="audit_snapshot")
        return response.status_code == 200
    except:
        return False

def get_audit_snapshot() -> Dict[str, Any]:
    """Generate audit snapshot"""
    db = SessionLocal()
    results: Dict[str, Any] = {
        "timestamp": time.time(),
        "health": {},
        "watchlist": {},
        "alerts": {},
        "orders": {},
        "performance": {},
        "reports": {}
    }
    
    try:
        api_url = get_api_url()
        
        # Service health
        backend_ok = check_service_health("Backend", f"{api_url}/api/ping_fast")
        results["health"]["backend"] = "OK" if backend_ok else "FAILED"
        
        # Watchlist deduplication
        try:
            all_items = db.query(WatchlistItem).filter(WatchlistItem.is_deleted == False).all()
            canonical_items = deduplicate_watchlist_items(all_items)
            duplicates = len(all_items) - len(canonical_items)
            unique_symbols = len(set(item.symbol.upper() for item in canonical_items))
            
            results["watchlist"]["symbols"] = unique_symbols
            results["watchlist"]["duplicates"] = duplicates
            results["watchlist"]["status"] = "OK" if duplicates == 0 else "WARNING"
        except Exception as e:
            results["watchlist"]["error"] = str(e)
            results["watchlist"]["status"] = "ERROR"
        
        # Active alerts
        try:
            buy_alerts = db.query(WatchlistItem).filter(
                WatchlistItem.is_deleted == False,
                WatchlistItem.buy_alert_enabled == True
            ).count()
            sell_alerts = db.query(WatchlistItem).filter(
                WatchlistItem.is_deleted == False,
                WatchlistItem.sell_alert_enabled == True
            ).count()
            
            results["alerts"]["buy"] = buy_alerts
            results["alerts"]["sell"] = sell_alerts
        except Exception as e:
            results["alerts"]["error"] = str(e)
        
        # Open orders
        try:
            open_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.status.in_([
                    OrderStatusEnum.NEW,
                    OrderStatusEnum.ACTIVE,
                    OrderStatusEnum.PARTIALLY_FILLED
                ])
            ).count()
            
            results["orders"]["count"] = open_orders
            results["orders"]["status"] = "OK" if open_orders <= 3 else "WARNING"
        except Exception as e:
            results["orders"]["error"] = str(e)
        
        # Watchlist load time
        if backend_ok:
            try:
                start_time = time.time()
                response = http_get(f"{api_url}/api/dashboard/state", timeout=10, calling_module="audit_snapshot")
                elapsed_ms = int((time.time() - start_time) * 1000)
                
                results["performance"]["watchlist_load_ms"] = elapsed_ms
                results["performance"]["status"] = "OK" if elapsed_ms <= 2000 else "WARNING"
            except Exception as e:
                results["performance"]["error"] = str(e)
        
        # Reports status
        if backend_ok:
            try:
                response = http_get(f"{api_url}/api/reports/dashboard-data-integrity/latest", timeout=5, calling_module="audit_snapshot")
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, dict) and data.get("status") == "success":
                        report_data = data.get("report", {})
                        inconsistencies = report_data.get("inconsistencies", [])
                        results["reports"]["inconsistencies"] = len(inconsistencies)
                        results["reports"]["status"] = "OK"
                    else:
                        results["reports"]["status"] = "NO_REPORT"
                else:
                    results["reports"]["status"] = "UNAVAILABLE"
            except Exception as e:
                results["reports"]["error"] = str(e)
                results["reports"]["status"] = "ERROR"
        
    finally:
        db.close()
    
    return results

def print_snapshot(results: Dict[str, Any]) -> None:
    """Print snapshot in human-readable format"""
    print("🔍 Audit Snapshot")
    print("=" * 50)
    print("")
    
    # Health
    print("📊 Service Health:")
    print(f"  Backend: {'✅ OK' if results['health'].get('backend') == 'OK' else '❌ FAILED'}")
    print("")
    
    # Watchlist
    if "watchlist" in results:
        wl = results["watchlist"]
        print("📋 Watchlist:")
        if "symbols" in wl:
            print(f"  Symbols: {wl['symbols']}")
            duplicates = wl.get("duplicates", 0)
            if duplicates > 0:
                print(f"  ⚠️  Duplicates: {duplicates}")
            else:
                print("  ✅ Duplicates: 0")
        elif "error" in wl:
            print(f"  ⚠️  Error: {wl['error']}")
        print("")
    
    # Alerts
    if "alerts" in results:
        alerts = results["alerts"]
        if "buy" in alerts:
            print("🔔 Active Alerts:")
            print(f"  BUY: {alerts['buy']}")
            print(f"  SELL: {alerts['sell']}")
        elif "error" in alerts:
            print(f"🔔 Alerts: ⚠️  Error: {alerts['error']}")
        print("")
    
    # Orders
    if "orders" in results:
        orders = results["orders"]
        if "count" in orders:
            count = orders["count"]
            print(f"📦 Open Orders: {count}")
            if count > 3:
                print("  ⚠️  Warning: More than 3 open orders")
        elif "error" in orders:
            print(f"📦 Orders: ⚠️  Error: {orders['error']}")
        print("")
    
    # Performance
    if "performance" in results:
        perf = results["performance"]
        if "watchlist_load_ms" in perf:
            ms = perf["watchlist_load_ms"]
            print(f"⏱️  Watchlist Load: {ms}ms")
            if ms > 2000:
                print("  ⚠️  Warning: Load time exceeds 2 seconds")
        elif "error" in perf:
            print(f"⏱️  Performance: ⚠️  Error: {perf['error']}")
        print("")
    
    # Reports
    if "reports" in results:
        reports = results["reports"]
        status = reports.get("status", "UNKNOWN")
        if status == "OK":
            inc = reports.get("inconsistencies", 0)
            print(f"📊 Reports: ✅ OK ({inc} inconsistencies)")
        else:
            print(f"📊 Reports: ⚠️  {status}")
        print("")
    
    print("=" * 50)

if __name__ == "__main__":
    try:
        results = get_audit_snapshot()
        print_snapshot(results)
        
        # Exit with error code if critical issues found
        if results["health"].get("backend") != "OK":
            sys.exit(1)
        if results.get("watchlist", {}).get("duplicates", 0) > 0:
            sys.exit(1)
        sys.exit(0)
    except Exception as e:
        print(f"❌ Error generating audit snapshot: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

