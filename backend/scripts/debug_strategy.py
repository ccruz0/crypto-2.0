#!/usr/bin/env python3
"""
Debug script to inspect strategy decisions for a specific symbol.

Usage:
    python backend/scripts/debug_strategy.py ALGO_USDT
    python backend/scripts/debug_strategy.py ALGO_USDT --last 50
    python backend/scripts/debug_strategy.py ALGO_USDT --grep "decision=BUY"
"""

import sys
import re
import subprocess
import argparse
from typing import List, Dict, Optional
from datetime import datetime


def parse_log_line(line: str) -> Optional[Dict]:
    """Parse a DEBUG_STRATEGY_FINAL log line into a structured dict."""
    # New format: DEBUG_STRATEGY_FINAL | symbol=ALGO_USDT | decision=WAIT | buy_signal=False | buy_rsi_ok=True | buy_volume_ok=True | buy_ma_ok=False | buy_target_ok=True | buy_price_ok=True | volume_ratio=1.3451 | min_volume_ratio=0.5000
    pattern_new = r'DEBUG_STRATEGY_FINAL \| symbol=(\S+) \| decision=(\S+) \| buy_signal=(\S+) \| ' \
                  r'buy_rsi_ok=(\S+) \| buy_volume_ok=(\S+) \| buy_ma_ok=(\S+) \| buy_target_ok=(\S+) \| buy_price_ok=(\S+)' \
                  r'(?: \| volume_ratio=([\d.]+) \| min_volume_ratio=([\d.]+))?'
    match = re.search(pattern_new, line)
    if match:
        symbol, decision, buy_signal, buy_rsi_ok, buy_volume_ok, buy_ma_ok, buy_target_ok, buy_price_ok, volume_ratio_str, min_volume_ratio_str = match.groups()
        
        # Build reasons dict from parsed flags
        reasons = {
            'buy_rsi_ok': True if buy_rsi_ok == 'True' else False if buy_rsi_ok == 'False' else None,
            'buy_volume_ok': True if buy_volume_ok == 'True' else False if buy_volume_ok == 'False' else None,
            'buy_ma_ok': True if buy_ma_ok == 'True' else False if buy_ma_ok == 'False' else None,
            'buy_target_ok': True if buy_target_ok == 'True' else False if buy_target_ok == 'False' else None,
            'buy_price_ok': True if buy_price_ok == 'True' else False if buy_price_ok == 'False' else None,
        }
        
        # Parse numeric values
        try:
            volume_ratio = float(volume_ratio_str) if volume_ratio_str else None
        except (ValueError, TypeError):
            volume_ratio = None
        price = rsi = buy_target = ma50 = ema10 = ma200 = None
    else:
        # Fallback to old format with reasons dict
        pattern_old = r'\[DEBUG_STRATEGY_FINAL\] symbol=(\S+) decision=(\S+) buy=(\S+) reasons=({.*?})'
        match = re.search(pattern_old, line)
        if not match:
            return None
        symbol, decision, buy_signal, reasons_str = match.groups()
        price = rsi = buy_target = volume_ratio = ma50 = ema10 = ma200 = None
        reasons = {}
    
    # Parse reasons dict (only if not already set from new format)
    if 'reasons' not in locals() or not reasons:
        reasons = {}
        try:
            # Extract key-value pairs from the reasons string
            reason_pattern = r"'(\w+)':\s*(True|False|None)"
            for key, value in re.findall(reason_pattern, reasons_str):
                if value == 'True':
                    reasons[key] = True
                elif value == 'False':
                    reasons[key] = False
                else:
                    reasons[key] = None
        except Exception:
            pass
    
    # Extract timestamp if present
    timestamp = None
    timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
    if timestamp_match:
        try:
            timestamp = datetime.strptime(timestamp_match.group(1), '%Y-%m-%d %H:%M:%S')
        except Exception:
            pass
    
    return {
        'symbol': symbol,
        'decision': decision,
        'buy_signal': buy_signal == 'True',
        'reasons': reasons,
        'timestamp': timestamp,
        'raw_line': line.strip(),
        'price': price,
        'rsi': rsi,
        'buy_target': buy_target,
        'volume_ratio': volume_ratio,
        'ma50': ma50,
        'ema10': ema10,
        'ma200': ma200,
    }


def get_docker_logs(container_name: str, symbol: str, last_n: int = 20) -> List[str]:
    """Get DEBUG_STRATEGY_FINAL logs for a symbol from docker logs."""
    try:
        cmd = [
            'docker', 'logs', container_name,
            '--tail', str(last_n * 100),  # Get more lines to filter (increased for better coverage)
            '2>&1'
        ]
        result = subprocess.run(
            ' '.join(cmd),
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            print(f"⚠️  Error running docker logs: {result.stderr}", file=sys.stderr)
            return []
        
        lines = result.stdout.split('\n')
        # Filter for DEBUG_STRATEGY_FINAL and symbol
        filtered = [
            line for line in lines
            if 'DEBUG_STRATEGY_FINAL' in line and symbol.upper() in line.upper()
        ]
        return filtered[-last_n:]  # Return last N matches
        
    except subprocess.TimeoutExpired:
        print("⚠️  Timeout reading docker logs", file=sys.stderr)
        return []
    except Exception as e:
        print(f"⚠️  Error: {e}", file=sys.stderr)
        return []


def compare_entries(entry1: Dict, entry2: Dict) -> Dict:
    """Compare two log entries and identify what changed."""
    changes = {
        'decision_changed': entry1['decision'] != entry2['decision'],
        'buy_signal_changed': entry1['buy_signal'] != entry2['buy_signal'],
        'flags_flipped': {},
        'flags_added': {},
        'flags_removed': {},
    }
    
    reasons1 = entry1.get('reasons', {})
    reasons2 = entry2.get('reasons', {})
    
    all_keys = set(reasons1.keys()) | set(reasons2.keys())
    
    for key in all_keys:
        val1 = reasons1.get(key)
        val2 = reasons2.get(key)
        
        if val1 != val2:
            if key in reasons1 and key in reasons2:
                changes['flags_flipped'][key] = (val1, val2)
            elif key in reasons1:
                changes['flags_removed'][key] = val1
            else:
                changes['flags_added'][key] = val2
    
    return changes


def format_entry(entry: Dict, index: int) -> str:
    """Format a log entry for display."""
    lines = []
    lines.append(f"\n{'='*80}")
    lines.append(f"Entry #{index} - {entry['symbol']}")
    if entry['timestamp']:
        lines.append(f"Timestamp: {entry['timestamp']}")
    lines.append(f"Decision: {entry['decision']} | Buy Signal: {entry['buy_signal']}")
    
    # Raw numeric values
    lines.append(f"\nRaw Values (unrounded):")
    if entry.get('price') is not None:
        lines.append(f"  price:        {entry['price']:.8f}")
    if entry.get('rsi') is not None:
        lines.append(f"  rsi:          {entry['rsi']:.4f}")
    if entry.get('buy_target') is not None:
        lines.append(f"  buy_target:   {entry['buy_target']:.8f}")
        if entry.get('price') is not None:
            diff = entry['price'] - entry['buy_target']
            lines.append(f"  price - target: {diff:.8f} {'✓' if diff <= 0 else '✗'}")
    if entry.get('volume_ratio') is not None:
        lines.append(f"  volume_ratio: {entry['volume_ratio']:.6f}")
    if entry.get('ma50') is not None:
        lines.append(f"  ma50:         {entry['ma50']:.8f}")
    if entry.get('ema10') is not None:
        lines.append(f"  ema10:        {entry['ema10']:.8f}")
    if entry.get('ma200') is not None:
        lines.append(f"  ma200:        {entry['ma200']:.8f}")
    
    lines.append(f"\nBuy Flags:")
    buy_flags = {k: v for k, v in entry['reasons'].items() if k.startswith('buy_')}
    for flag, value in sorted(buy_flags.items()):
        status = '✓' if value is True else '✗' if value is False else '?'
        lines.append(f"  {flag:20s} = {str(value):5s} {status}")
    
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Debug strategy decisions for a symbol')
    parser.add_argument('symbol', help='Symbol to debug (e.g., ALGO_USDT)')
    parser.add_argument('--container', default='automated-trading-platform-backend-aws-1',
                       help='Docker container name')
    parser.add_argument('--last', type=int, default=20,
                       help='Number of recent log entries to show')
    parser.add_argument('--grep', help='Additional grep filter (e.g., "decision=BUY")')
    parser.add_argument('--compare', action='store_true',
                       help='Compare consecutive entries to find flips')
    
    args = parser.parse_args()
    
    print(f"🔍 Fetching strategy logs for {args.symbol}...")
    print(f"   Container: {args.container}")
    print(f"   Last {args.last} entries\n")
    
    # Get logs
    logs = get_docker_logs(args.container, args.symbol, args.last * 2)
    
    if args.grep:
        logs = [line for line in logs if args.grep in line]
    
    if not logs:
        print(f"❌ No logs found for {args.symbol}")
        print("\n💡 Try:")
        print(f"   docker logs {args.container} --tail 10000 | grep DEBUG_STRATEGY_FINAL | grep {args.symbol}")
        return 1
    
    # Parse entries
    entries = []
    for line in logs:
        entry = parse_log_line(line)
        if entry:
            entries.append(entry)
    
    if not entries:
        print(f"❌ Could not parse any log entries")
        return 1
    
    # Show last N entries
    entries = entries[-args.last:]
    
    print(f"📊 Found {len(entries)} entries\n")
    
    # Display entries
    for i, entry in enumerate(entries, 1):
        print(format_entry(entry, i))
    
    # Compare consecutive entries if requested
    if args.compare and len(entries) >= 2:
        print(f"\n{'='*80}")
        print("🔍 COMPARING CONSECUTIVE ENTRIES")
        print(f"{'='*80}\n")
        
        for i in range(len(entries) - 1):
            entry1 = entries[i]
            entry2 = entries[i + 1]
            
            if entry1['decision'] != entry2['decision'] or entry1['buy_signal'] != entry2['buy_signal']:
                print(f"\n⚠️  FLIP DETECTED between Entry #{i+1} and Entry #{i+2}")
                print(f"   {entry1['decision']} → {entry2['decision']}")
                print(f"   buy_signal: {entry1['buy_signal']} → {entry2['buy_signal']}")
                
                changes = compare_entries(entry1, entry2)
                
                if changes['flags_flipped']:
                    print(f"\n   Flags that flipped:")
                    for flag, (old_val, new_val) in changes['flags_flipped'].items():
                        print(f"     {flag}: {old_val} → {new_val}")
                        if old_val is True and new_val is False:
                            print(f"       ⚠️  This flag going False caused BUY → WAIT!")
                            
                            # Show relevant numeric values that caused the flip
                            if flag == 'buy_target_ok':
                                if entry1.get('price') and entry1.get('buy_target'):
                                    print(f"       Entry #{i+1}: price={entry1['price']:.8f}, buy_target={entry1['buy_target']:.8f}, diff={entry1['price'] - entry1['buy_target']:.8f}")
                                if entry2.get('price') and entry2.get('buy_target'):
                                    print(f"       Entry #{i+2}: price={entry2['price']:.8f}, buy_target={entry2['buy_target']:.8f}, diff={entry2['price'] - entry2['buy_target']:.8f}")
                            elif flag == 'buy_rsi_ok':
                                if entry1.get('rsi') is not None:
                                    print(f"       Entry #{i+1}: rsi={entry1['rsi']:.4f}")
                                if entry2.get('rsi') is not None:
                                    print(f"       Entry #{i+2}: rsi={entry2['rsi']:.4f}")
                            elif flag == 'buy_volume_ok':
                                if entry1.get('volume_ratio') is not None:
                                    print(f"       Entry #{i+1}: volume_ratio={entry1['volume_ratio']:.6f}")
                                if entry2.get('volume_ratio') is not None:
                                    print(f"       Entry #{i+2}: volume_ratio={entry2['volume_ratio']:.6f}")
                            elif flag == 'buy_ma_ok':
                                if entry1.get('ma50') and entry1.get('ema10'):
                                    print(f"       Entry #{i+1}: ma50={entry1['ma50']:.8f}, ema10={entry1['ema10']:.8f}")
                                if entry2.get('ma50') and entry2.get('ema10'):
                                    print(f"       Entry #{i+2}: ma50={entry2['ma50']:.8f}, ema10={entry2['ema10']:.8f}")
    
    print(f"\n{'='*80}")
    print("💡 To see raw log lines, check docker logs directly:")
    print(f"   docker logs {args.container} --tail 10000 | grep DEBUG_STRATEGY_FINAL | grep {args.symbol} | tail -{args.last}")
    print(f"{'='*80}\n")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

