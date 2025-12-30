#!/usr/bin/env python3
"""Monitor backend logs for trade_enabled limit issues.

This script monitors backend logs for:
- When trade_enabled is enabled/disabled
- Count mismatches that suggest automatic disabling
- Any warnings about trade_enabled limits

Usage:
    python backend/scripts/monitor_trade_enabled_limit.py
    # Or with log file:
    tail -f /path/to/backend.log | python backend/scripts/monitor_trade_enabled_limit.py
"""

import sys
import re
import json
from datetime import datetime
from typing import Dict, List, Optional

# Patterns to look for in logs
PATTERNS = {
    'trade_enabled_enable': re.compile(
        r'\[TRADE_ENABLED_ENABLE\].*?Enabling trade_enabled for (\w+).*?Current count.*?(\d+).*?After.*?(\d+)'
    ),
    'trade_enabled_disable': re.compile(
        r'\[TRADE_ENABLED_DISABLE\].*?Disabling trade_enabled for (\w+).*?Current count.*?(\d+)'
    ),
    'count_mismatch': re.compile(
        r'\[TRADE_ENABLED_COUNT_MISMATCH\].*?Unexpected count change.*?Before.*?(\d+).*?After.*?(\d+).*?Expected.*?(\d+)'
    ),
    'count_verified': re.compile(
        r'\[TRADE_ENABLED_COUNT_VERIFIED\].*?Count verified.*?Before.*?(\d+).*?After.*?(\d+).*?Expected.*?(\d+)'
    ),
    'watchlist_update': re.compile(
        r'\[WATCHLIST_UPDATE\].*?PUT.*?for (\w+).*?updating fields.*?trade_enabled'
    ),
}

def parse_log_line(line: str) -> Optional[Dict]:
    """Parse a log line and extract relevant information."""
    result = {}
    
    # Check for trade_enabled enable
    match = PATTERNS['trade_enabled_enable'].search(line)
    if match:
        result['type'] = 'enable'
        result['symbol'] = match.group(1)
        result['current_count'] = int(match.group(2))
        result['expected_count'] = int(match.group(3))
        return result
    
    # Check for trade_enabled disable
    match = PATTERNS['trade_enabled_disable'].search(line)
    if match:
        result['type'] = 'disable'
        result['symbol'] = match.group(1)
        result['current_count'] = int(match.group(2))
        return result
    
    # Check for count mismatch (this is the key indicator!)
    match = PATTERNS['count_mismatch'].search(line)
    if match:
        result['type'] = 'mismatch'
        result['before'] = int(match.group(1))
        result['after'] = int(match.group(2))
        result['expected'] = int(match.group(3))
        return result
    
    # Check for count verified
    match = PATTERNS['count_verified'].search(line)
    if match:
        result['type'] = 'verified'
        result['before'] = int(match.group(1))
        result['after'] = int(match.group(2))
        result['expected'] = int(match.group(3))
        return result
    
    # Check for watchlist update
    match = PATTERNS['watchlist_update'].search(line)
    if match:
        result['type'] = 'update'
        result['symbol'] = match.group(1)
        return result
    
    return None

def format_event(event: Dict, timestamp: str = None) -> str:
    """Format an event for display."""
    timestamp_str = timestamp or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    if event['type'] == 'enable':
        return (
            f"[{timestamp_str}] ✅ ENABLING {event['symbol']}: "
            f"Current={event['current_count']}, Expected={event['expected_count']}"
        )
    elif event['type'] == 'disable':
        return (
            f"[{timestamp_str}] ❌ DISABLING {event['symbol']}: "
            f"Current={event['current_count']}"
        )
    elif event['type'] == 'mismatch':
        return (
            f"[{timestamp_str}] 🚨 COUNT MISMATCH DETECTED! "
            f"Before={event['before']}, After={event['after']}, Expected={event['expected']} "
            f"(Difference: {event['after'] - event['expected']})"
        )
    elif event['type'] == 'verified':
        return (
            f"[{timestamp_str}] ✅ Count verified: "
            f"Before={event['before']}, After={event['after']}, Expected={event['expected']}"
        )
    elif event['type'] == 'update':
        return (
            f"[{timestamp_str}] 🔄 Updating {event['symbol']} (trade_enabled change)"
        )
    
    return f"[{timestamp_str}] {json.dumps(event)}"

def main():
    """Main monitoring loop."""
    print("🔍 Monitoring backend logs for trade_enabled limit issues...")
    print("=" * 80)
    print("Looking for:")
    print("  - Trade enabled/disabled events")
    print("  - Count mismatches (indicates automatic disabling)")
    print("  - Count verifications")
    print("=" * 80)
    print()
    
    event_history: List[Dict] = []
    current_count = None
    
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            
            # Try to extract timestamp from log line
            timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2})', line)
            timestamp = timestamp_match.group(1) if timestamp_match else None
            
            event = parse_log_line(line)
            if event:
                event_history.append(event)
                print(format_event(event, timestamp))
                
                # Track current count
                if 'current_count' in event:
                    current_count = event['current_count']
                elif 'after' in event:
                    current_count = event['after']
                
                # Alert on mismatches
                if event['type'] == 'mismatch':
                    print()
                    print("⚠️" * 40)
                    print("⚠️  AUTOMATIC DISABLING DETECTED!")
                    print("⚠️" * 40)
                    print()
                    print(f"   Expected count: {event['expected']}")
                    print(f"   Actual count: {event['after']}")
                    print(f"   Difference: {event['after'] - event['expected']} coins were automatically disabled!")
                    print()
                    
                    # Show recent history
                    print("Recent events:")
                    for e in event_history[-5:]:
                        print(f"  - {format_event(e)}")
                    print()
    
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")
        print(f"\nTotal events captured: {len(event_history)}")
        if current_count is not None:
            print(f"Current trade_enabled count: {current_count}")

if __name__ == '__main__':
    main()


