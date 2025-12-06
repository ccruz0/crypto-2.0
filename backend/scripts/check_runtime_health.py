#!/usr/bin/env python3
"""
Runtime health check script for automated-trading-platform backend.

This script performs PASSIVE health checks only:
- Queries API endpoints (does NOT start services)
- Reads configuration (does NOT modify anything)
- Checks monitoring data (does NOT create alerts or orders)

It is safe to run from any environment (local Mac via SSH, or inside container).

Checks:
- API health endpoints
- Scheduler status
- SignalMonitorService configuration
- Recent alert activity

Exit code: 0 if healthy, non-zero if any critical check fails.
"""

import sys
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import requests
except ImportError:
    print("ERROR: requests module not installed. Install with: pip install requests")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8002"
CHECKS_PASSED = []
CHECKS_FAILED = []
WARNINGS = []


def check_api_health():
    """Check /api/health endpoint"""
    try:
        response = requests.get(f"{BASE_URL}/api/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "ok":
                CHECKS_PASSED.append("API health endpoint")
                return True
        CHECKS_FAILED.append(f"API health endpoint: HTTP {response.status_code}")
        return False
    except Exception as e:
        CHECKS_FAILED.append(f"API health endpoint: {e}")
        return False


def check_dashboard_snapshot():
    """Check /api/dashboard/snapshot endpoint"""
    try:
        response = requests.get(f"{BASE_URL}/api/dashboard/snapshot", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if "data" in data:
                CHECKS_PASSED.append("Dashboard snapshot endpoint")
                return True
        CHECKS_FAILED.append(f"Dashboard snapshot: HTTP {response.status_code}")
        return False
    except Exception as e:
        CHECKS_FAILED.append(f"Dashboard snapshot: {e}")
        return False


def check_monitoring_summary():
    """Check /api/monitoring/summary endpoint"""
    try:
        response = requests.get(f"{BASE_URL}/api/monitoring/summary", timeout=10)
        if response.status_code == 200:
            data = response.json()
            CHECKS_PASSED.append("Monitoring summary endpoint")
            
            # Check for scheduler ticks
            scheduler_ticks = data.get("scheduler_ticks", 0)
            if scheduler_ticks == 0:
                WARNINGS.append("Scheduler ticks = 0 (scheduler may not be running)")
            
            return True
        CHECKS_FAILED.append(f"Monitoring summary: HTTP {response.status_code}")
        return False
    except Exception as e:
        CHECKS_FAILED.append(f"Monitoring summary: {e}")
        return False


def check_signal_monitor_config():
    """Check if SignalMonitorService is configured to run"""
    try:
        # Try to import and check the config
        from app.main import DEBUG_DISABLE_SIGNAL_MONITOR
        if DEBUG_DISABLE_SIGNAL_MONITOR:
            CHECKS_FAILED.append("SignalMonitorService is DISABLED (DEBUG_DISABLE_SIGNAL_MONITOR=True)")
            return False
        else:
            CHECKS_PASSED.append("SignalMonitorService is ENABLED (DEBUG_DISABLE_SIGNAL_MONITOR=False)")
            return True
    except Exception as e:
        WARNINGS.append(f"Could not check SignalMonitorService config: {e}")
        return True  # Don't fail on this, just warn


def check_recent_alerts():
    """Check for recent alerts in /api/monitoring/telegram-messages"""
    try:
        response = requests.get(f"{BASE_URL}/api/monitoring/telegram-messages?limit=5", timeout=10)
        if response.status_code == 200:
            data = response.json()
            messages = data.get("messages", [])
            
            if not messages:
                WARNINGS.append("No recent alerts found in Monitoring (may be normal if no BUY signals)")
                return True
            
            # Check timestamp of most recent alert
            most_recent = messages[0]
            timestamp_str = most_recent.get("timestamp")
            if timestamp_str:
                try:
                    # Parse ISO format timestamp
                    alert_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    now = datetime.now(alert_time.tzinfo)
                    age_minutes = (now - alert_time).total_seconds() / 60
                    
                    if age_minutes < 60:
                        CHECKS_PASSED.append(f"Recent alerts found (last alert {age_minutes:.1f} minutes ago)")
                    elif age_minutes < 120:
                        WARNINGS.append(f"Last alert was {age_minutes:.1f} minutes ago (may indicate no BUY signals)")
                    else:
                        WARNINGS.append(f"Last alert was {age_minutes:.1f} minutes ago (>2 hours - may indicate issue)")
                except Exception as e:
                    WARNINGS.append(f"Could not parse alert timestamp: {e}")
            
            return True
        CHECKS_FAILED.append(f"Telegram messages endpoint: HTTP {response.status_code}")
        return False
    except Exception as e:
        WARNINGS.append(f"Could not check recent alerts: {e}")
        return True  # Don't fail on this, just warn


def main():
    """Run all health checks"""
    print("=" * 60)
    print("Runtime Health Check - automated-trading-platform")
    print("=" * 60)
    print()
    
    # Run checks
    check_api_health()
    check_dashboard_snapshot()
    check_monitoring_summary()
    check_signal_monitor_config()
    check_recent_alerts()
    
    # Print results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    
    if CHECKS_PASSED:
        print("\n✅ PASSED:")
        for check in CHECKS_PASSED:
            print(f"  - {check}")
    
    if WARNINGS:
        print("\n⚠️  WARNINGS:")
        for warning in WARNINGS:
            print(f"  - {warning}")
    
    if CHECKS_FAILED:
        print("\n❌ FAILED:")
        for check in CHECKS_FAILED:
            print(f"  - {check}")
    
    print()
    
    # Exit code
    if CHECKS_FAILED:
        print("❌ Health check FAILED")
        sys.exit(1)
    elif WARNINGS:
        print("⚠️  Health check passed with warnings")
        sys.exit(0)
    else:
        print("✅ All health checks passed")
        sys.exit(0)


if __name__ == "__main__":
    main()

