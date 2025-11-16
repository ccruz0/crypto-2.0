#!/usr/bin/env python3
"""
Script to analyze TP order errors and compare payloads.
This helps identify what's causing errors 229/40004.
"""
import sys
import json
import re
from collections import defaultdict

def extract_payload_from_logs(log_text):
    """Extract the most recent MANUAL TP payload from logs"""
    lines = log_text.split('\n')
    
    # Find the most recent FULL PAYLOAD line
    for line in reversed(lines):
        if 'FULL PAYLOAD:' in line and 'MANUAL' in log_text:
            # Extract the dict from the line
            payload_match = re.search(r"FULL PAYLOAD:\s*({.+})", line)
            if payload_match:
                try:
                    payload_str = payload_match.group(1).replace("'", '"')
                    return json.loads(payload_str)
                except:
                    pass
    
    # Alternative: find Payload JSON
    current_payload = None
    in_payload = False
    payload_lines = []
    
    for line in lines:
        if '[TP_ORDER][MANUAL]' in line and 'Payload JSON:' in line:
            in_payload = True
            payload_lines = [line]
            continue
        
        if in_payload:
            payload_lines.append(line)
            if line.strip().startswith('}'):
                # Try to parse
                payload_text = '\n'.join(payload_lines)
                json_match = re.search(r'Payload JSON:\s*(\{.*\})', payload_text, re.DOTALL)
                if json_match:
                    try:
                        current_payload = json.loads(json_match.group(1))
                        break
                    except:
                        pass
                in_payload = False
                payload_lines = []
    
    return current_payload

def analyze_payload(payload):
    """Analyze a payload and identify potential issues"""
    issues = []
    
    if not payload:
        return ["No payload found"]
    
    params = payload.get('params', {})
    
    # Check required fields
    required_fields = ['instrument_name', 'type', 'price', 'quantity', 'trigger_price']
    for field in required_fields:
        if field not in params:
            issues.append(f"❌ MISSING REQUIRED FIELD: {field}")
    
    # Check ref_price
    if 'ref_price' not in params:
        issues.append("⚠️  MISSING ref_price (required for TAKE_PROFIT_LIMIT)")
    else:
        ref_price = params.get('ref_price')
        trigger_price = params.get('trigger_price')
        price = params.get('price')
        
        # Check if ref_price matches expected format
        if ref_price and trigger_price:
            try:
                ref_val = float(ref_price)
                trigger_val = float(trigger_price)
                price_val = float(price)
                
                # According to comments, ref_price should be entry_price, not TP price
                # But trigger_price and price should be equal (both TP price)
                if trigger_val != price_val:
                    issues.append(f"⚠️  trigger_price ({trigger_val}) != price ({price_val}) - should be equal")
                
                # ref_price should be entry_price (lower than TP for long positions)
                if ref_val >= trigger_val:
                    issues.append(f"⚠️  ref_price ({ref_val}) >= trigger_price ({trigger_val}) - ref_price should be entry_price (lower)")
            except:
                issues.append(f"⚠️  Could not parse ref_price/trigger_price as numbers")
    
    # Check trigger_condition
    if 'trigger_condition' not in params:
        issues.append("⚠️  MISSING trigger_condition")
    else:
        trigger_condition = params.get('trigger_condition')
        trigger_price = params.get('trigger_price')
        
        # trigger_condition should be ">= {trigger_price}"
        if trigger_price:
            expected = f">= {trigger_price}"
            if trigger_condition != expected:
                issues.append(f"⚠️  trigger_condition mismatch: got '{trigger_condition}', expected '{expected}'")
    
    # Check side
    if 'side' not in params:
        issues.append("⚠️  MISSING side field")
    else:
        side = params.get('side')
        if side not in ['SELL', 'sell', 'BUY', 'buy']:
            issues.append(f"⚠️  side format might be wrong: '{side}' (should be SELL/sell/BUY/buy)")
    
    # Check type
    if params.get('type') != 'TAKE_PROFIT_LIMIT':
        issues.append(f"⚠️  type is '{params.get('type')}', should be 'TAKE_PROFIT_LIMIT'")
    
    return issues

def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: python3 analyze_tp_errors.py <log_file>")
        print("Or pipe logs: docker compose logs backend-aws 2>&1 | python3 analyze_tp_errors.py -")
        sys.exit(1)
    
    if sys.argv[1] == '-':
        log_text = sys.stdin.read()
    else:
        with open(sys.argv[1], 'r') as f:
            log_text = f.read()
    
    print("="*80)
    print("ANALYZING TP ORDER PAYLOADS")
    print("="*80)
    
    # Extract payload
    payload = extract_payload_from_logs(log_text)
    
    if payload:
        print("\n📦 Extracted Payload:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        
        print("\n" + "="*80)
        print("ANALYSIS")
        print("="*80)
        
        issues = analyze_payload(payload)
        
        if issues:
            print("\n⚠️  Found potential issues:")
            for issue in issues:
                print(f"  {issue}")
        else:
            print("\n✅ No obvious issues found in payload structure")
        
        # Show params breakdown
        params = payload.get('params', {})
        print("\n" + "="*80)
        print("PAYLOAD PARAMS BREAKDOWN")
        print("="*80)
        print(f"instrument_name: {params.get('instrument_name')}")
        print(f"type: {params.get('type')}")
        print(f"side: {params.get('side', 'MISSING')}")
        print(f"price: {params.get('price')} (execution price = TP price)")
        print(f"trigger_price: {params.get('trigger_price')} (should equal price)")
        print(f"ref_price: {params.get('ref_price', 'MISSING')} (should be entry_price)")
        print(f"trigger_condition: {params.get('trigger_condition', 'MISSING')}")
        print(f"quantity: {params.get('quantity')}")
        print(f"time_in_force: {params.get('time_in_force', 'NOT SET')}")
        print(f"client_oid: {params.get('client_oid', 'NOT SET')}")
        
        # Check for common error patterns
        print("\n" + "="*80)
        print("ERROR PATTERN ANALYSIS")
        print("="*80)
        
        # Error 229: INVALID_REF_PRICE
        ref_price = params.get('ref_price')
        if ref_price:
            try:
                ref_val = float(ref_price)
                trigger_val = float(params.get('trigger_price', 0))
                
                # Crypto.com might expect ref_price to be current market price or trigger_price
                # But we're using entry_price. This could be the issue.
                print(f"\n🔍 Error 229 (INVALID_REF_PRICE) analysis:")
                print(f"   Current ref_price: {ref_val} (entry_price)")
                print(f"   trigger_price: {trigger_val} (TP price)")
                print(f"   Difference: {trigger_val - ref_val}")
                print(f"   ⚠️  Crypto.com might expect ref_price = trigger_price (TP price)")
                print(f"   ⚠️  But we're using ref_price = entry_price")
            except:
                print(f"   Could not analyze ref_price format")
        
        # Error 40004: Missing or invalid argument
        print(f"\n🔍 Error 40004 (Missing or invalid argument) analysis:")
        missing_fields = []
        if 'side' not in params:
            missing_fields.append('side')
        if 'ref_price' not in params:
            missing_fields.append('ref_price')
        if 'trigger_condition' not in params:
            missing_fields.append('trigger_condition')
        
        if missing_fields:
            print(f"   Missing fields: {', '.join(missing_fields)}")
        else:
            print(f"   All required fields present")
            print(f"   ⚠️  Check field formats/values:")
            print(f"      - side format: '{params.get('side')}' (should be 'SELL' for TP)")
            print(f"      - ref_price format: '{params.get('ref_price')}' (might need to match trigger_price)")
            print(f"      - trigger_condition format: '{params.get('trigger_condition')}'")
    else:
        print("\n❌ Could not extract payload from logs")
        print("   Make sure logs contain [TP_ORDER][MANUAL] entries")
    
    print("\n" + "="*80)

if __name__ == '__main__':
    main()

