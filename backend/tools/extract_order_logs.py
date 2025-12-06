#!/usr/bin/env python3
"""
Extract logs for a specific order to diagnose SL/TP creation issues.
Usage: docker compose exec backend-aws python3 /app/tools/extract_order_logs.py ORDER_ID
"""
import sys
import subprocess
import re

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 extract_order_logs.py ORDER_ID [SYMBOL]")
        print("Example: python3 extract_order_logs.py 5755600477880747933 SOL_USDT")
        sys.exit(1)
    
    order_id = sys.argv[1]
    symbol = sys.argv[2] if len(sys.argv) > 2 else "SOL_USDT"
    
    print("="*80)
    print(f"EXTRACTING LOGS FOR ORDER {order_id} ({symbol})")
    print("="*80)
    print()
    
    # Get logs
    try:
        result = subprocess.run(
            ["docker", "compose", "logs", "backend-aws"],
            capture_output=True,
            text=True,
            check=False
        )
        logs = result.stdout + result.stderr
    except Exception as e:
        print(f"Error getting logs: {e}")
        sys.exit(1)
    
    # Extract relevant sections
    print("1. SL/TP CREATION ATTEMPT:")
    print("-"*80)
    sl_tp_pattern = f"Creating SL/TP for {symbol}.*{order_id}"
    for line in logs.split('\n'):
        if re.search(sl_tp_pattern, line, re.IGNORECASE):
            print(line)
            # Print next 30 lines
            idx = logs.split('\n').index(line)
            for i in range(idx+1, min(idx+31, len(logs.split('\n')))):
                print(logs.split('\n')[i])
            break
    print()
    
    print("2. SL ORDER HTTP LOGS:")
    print("-"*80)
    for line in logs.split('\n'):
        if "[SL_ORDER]" in line and symbol in line:
            print(line)
    print()
    
    print("3. TP ORDER HTTP LOGS:")
    print("-"*80)
    for line in logs.split('\n'):
        if "[TP_ORDER]" in line and symbol in line:
            print(line)
    print()
    
    print("4. ERRORS:")
    print("-"*80)
    error_keywords = ["error", "failed", "exception", "229", "40004", "220", "308"]
    for line in logs.split('\n'):
        if any(keyword in line.lower() for keyword in error_keywords):
            if symbol.lower() in line.lower() or order_id in line:
                print(line)
    print()
    
    print("5. FULL PAYLOAD LOGS:")
    print("-"*80)
    for line in logs.split('\n'):
        if "FULL PAYLOAD" in line or "Payload JSON" in line:
            print(line)
            # Print next 10 lines for context
            idx = logs.split('\n').index(line)
            for i in range(idx+1, min(idx+11, len(logs.split('\n')))):
                print(logs.split('\n')[i])
    print()
    
    print("="*80)
    print("LOG EXTRACTION COMPLETE")
    print("="*80)

if __name__ == '__main__':
    main()

