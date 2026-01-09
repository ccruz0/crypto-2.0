#!/usr/bin/env python3
"""
Test script for monitoring refresh functionality
Tests the new force_refresh parameter and signals_last_calculated timestamp
"""

import requests
import json
import time
from datetime import datetime
from typing import Dict, Any

# Configuration
BASE_URL = "http://localhost:8000/api"
# BASE_URL = "http://175.41.189.249:8000/api"  # Uncomment for AWS testing

def test_monitoring_summary_basic():
    """Test basic monitoring summary endpoint"""
    print("\n" + "="*60)
    print("TEST 1: Basic Monitoring Summary")
    print("="*60)
    
    try:
        response = requests.get(f"{BASE_URL}/monitoring/summary", timeout=30)
        response.raise_for_status()
        data = response.json()
        
        print(f"✅ Status Code: {response.status_code}")
        print(f"✅ Active Alerts: {data.get('active_alerts', 0)}")
        print(f"✅ Backend Health: {data.get('backend_health', 'unknown')}")
        print(f"✅ Signals Last Calculated: {data.get('signals_last_calculated', 'Not provided')}")
        
        if 'alerts' in data:
            print(f"✅ Alerts Count: {len(data['alerts'])}")
            if data['alerts']:
                print(f"   First Alert: {data['alerts'][0]}")
        
        return True, data
    except Exception as e:
        print(f"❌ Error: {e}")
        return False, None

def test_monitoring_summary_force_refresh():
    """Test monitoring summary with force_refresh parameter"""
    print("\n" + "="*60)
    print("TEST 2: Force Refresh Signals")
    print("="*60)
    
    try:
        # First, get baseline without force refresh
        print("📊 Getting baseline (no force refresh)...")
        baseline_response = requests.get(f"{BASE_URL}/monitoring/summary", timeout=30)
        baseline_response.raise_for_status()
        baseline_data = baseline_response.json()
        baseline_timestamp = baseline_data.get('signals_last_calculated')
        
        print(f"   Baseline timestamp: {baseline_timestamp}")
        
        # Wait a moment to ensure different timestamp
        time.sleep(2)
        
        # Now test with force refresh
        print("\n🔄 Testing with force_refresh=true...")
        refresh_response = requests.get(
            f"{BASE_URL}/monitoring/summary?force_refresh=true",
            timeout=60  # Longer timeout for force refresh
        )
        refresh_response.raise_for_status()
        refresh_data = refresh_response.json()
        refresh_timestamp = refresh_data.get('signals_last_calculated')
        
        print(f"   Refresh timestamp: {refresh_timestamp}")
        
        # Verify timestamp was updated
        if refresh_timestamp:
            print(f"✅ Force refresh returned timestamp: {refresh_timestamp}")
            
            # Parse timestamps for comparison
            if baseline_timestamp:
                baseline_dt = datetime.fromisoformat(baseline_timestamp.replace('Z', '+00:00'))
                refresh_dt = datetime.fromisoformat(refresh_timestamp.replace('Z', '+00:00'))
                
                if refresh_dt > baseline_dt:
                    print(f"✅ Timestamp updated correctly (refresh is newer)")
                else:
                    print(f"⚠️  Timestamp not updated (refresh is not newer)")
            else:
                print(f"✅ Timestamp provided (baseline had none)")
        else:
            print(f"⚠️  No timestamp in refresh response")
        
        # Compare alert counts
        baseline_alerts = baseline_data.get('active_alerts', 0)
        refresh_alerts = refresh_data.get('active_alerts', 0)
        
        print(f"\n📊 Alert Counts:")
        print(f"   Baseline: {baseline_alerts}")
        print(f"   After Refresh: {refresh_alerts}")
        
        if baseline_alerts == refresh_alerts:
            print(f"✅ Alert counts match (consistent)")
        else:
            print(f"⚠️  Alert counts differ (may be expected if signals changed)")
        
        return True, refresh_data
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False, None

def test_monitoring_summary_multiple_refreshes():
    """Test multiple force refreshes to verify consistency"""
    print("\n" + "="*60)
    print("TEST 3: Multiple Force Refreshes")
    print("="*60)
    
    try:
        timestamps = []
        alert_counts = []
        
        for i in range(3):
            print(f"\n🔄 Refresh #{i+1}...")
            response = requests.get(
                f"{BASE_URL}/monitoring/summary?force_refresh=true",
                timeout=60
            )
            response.raise_for_status()
            data = response.json()
            
            timestamp = data.get('signals_last_calculated')
            alert_count = data.get('active_alerts', 0)
            
            timestamps.append(timestamp)
            alert_counts.append(alert_count)
            
            print(f"   Timestamp: {timestamp}")
            print(f"   Alerts: {alert_count}")
            
            time.sleep(1)  # Small delay between requests
        
        # Verify all refreshes returned timestamps
        if all(timestamps):
            print(f"\n✅ All refreshes returned timestamps")
        else:
            print(f"\n⚠️  Some refreshes missing timestamps")
        
        # Check if timestamps are recent (within last minute)
        if timestamps:
            latest = timestamps[-1]
            if latest:
                latest_dt = datetime.fromisoformat(latest.replace('Z', '+00:00'))
                now = datetime.now(latest_dt.tzinfo)
                age_seconds = (now - latest_dt).total_seconds()
                
                if age_seconds < 60:
                    print(f"✅ Latest timestamp is recent ({age_seconds:.1f}s ago)")
                else:
                    print(f"⚠️  Latest timestamp is old ({age_seconds:.1f}s ago)")
        
        return True, {"timestamps": timestamps, "alert_counts": alert_counts}
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False, None

def test_response_structure():
    """Test that response structure includes all expected fields"""
    print("\n" + "="*60)
    print("TEST 4: Response Structure Validation")
    print("="*60)
    
    try:
        response = requests.get(f"{BASE_URL}/monitoring/summary", timeout=30)
        response.raise_for_status()
        data = response.json()
        
        required_fields = [
            'active_alerts',
            'backend_health',
            'last_sync_seconds',
            'portfolio_state_duration',
            'open_orders',
            'balances',
            'scheduler_ticks',
            'errors',
            'alerts',
            'signals_last_calculated'  # New field
        ]
        
        missing_fields = []
        for field in required_fields:
            if field not in data:
                missing_fields.append(field)
            else:
                print(f"✅ Field '{field}': {type(data[field]).__name__}")
        
        if missing_fields:
            print(f"\n❌ Missing fields: {missing_fields}")
            return False, data
        else:
            print(f"\n✅ All required fields present")
            return True, data
    except Exception as e:
        print(f"❌ Error: {e}")
        return False, None

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("MONITORING REFRESH FUNCTIONALITY TESTS")
    print("="*60)
    print(f"Testing endpoint: {BASE_URL}/monitoring/summary")
    print(f"Time: {datetime.now().isoformat()}")
    
    results = []
    
    # Test 1: Basic functionality
    success, data = test_monitoring_summary_basic()
    results.append(("Basic Summary", success))
    
    # Test 2: Force refresh
    success, data = test_monitoring_summary_force_refresh()
    results.append(("Force Refresh", success))
    
    # Test 3: Multiple refreshes
    success, data = test_monitoring_summary_multiple_refreshes()
    results.append(("Multiple Refreshes", success))
    
    # Test 4: Response structure
    success, data = test_response_structure()
    results.append(("Response Structure", success))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1

if __name__ == "__main__":
    exit(main())

