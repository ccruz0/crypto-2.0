#!/usr/bin/env python3
"""
Script to extract and compare TP order payloads from logs.
This searches for [TP_ORDER] log entries and extracts the JSON payloads.

Usage:
    docker compose logs backend-aws 2>&1 | python3 extract_payloads.py -
    python3 extract_payloads.py <log_file>
"""
import sys
import re
import json
from collections import defaultdict
from typing import Dict, List, Optional, Set

# Fields to ignore when comparing payloads (volatile fields)
VOLATILE_FIELDS = {
    'client_oid', 'nonce', 'sig', 'id', 'api_key',
    'request_id', 'timestamp', 'created_at', 'updated_at'
}

# Fields that should be compared but might have different formats
FORMAT_SENSITIVE_FIELDS = {
    'price', 'quantity', 'trigger_price', 'ref_price',
    'time_in_force', 'side', 'type', 'instrument_name'
}

def extract_payloads_from_logs(log_text: str) -> tuple[List[Dict], List[Dict]]:
    """
    Extract payloads from log text.
    
    Returns:
        (auto_payloads, manual_payloads) - Lists of payload entries
    """
    auto_payloads = []
    manual_payloads = []
    
    # Pattern to match [TP_ORDER][SOURCE][REQUEST_ID] entries
    pattern = r'\[TP_ORDER\]\[(AUTO|MANUAL)\]\[([^\]]+)\]\s+(Sending HTTP request|Received HTTP response)'
    
    current_entry = None
    current_source = None
    current_request_id = None
    
    lines = log_text.split('\n')
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Check if this is a TP_ORDER log entry header
        match = re.search(pattern, line)
        if match:
            source = match.group(1)
            request_id = match.group(2)
            action = match.group(3)
            
            current_source = source
            current_request_id = request_id
            current_entry = {
                'source': source,
                'request_id': request_id,
                'action': action,
                'payload': None,
                'response': None,
                'url': None,
                'method': None
            }
            
            if source == 'AUTO':
                auto_payloads.append(current_entry)
            else:
                manual_payloads.append(current_entry)
        
        # If we're in a TP_ORDER entry, look for details
        if current_entry:
            # Look for URL
            if 'URL:' in line and current_entry['url'] is None:
                url_match = re.search(r'URL:\s*(.+)', line)
                if url_match:
                    current_entry['url'] = url_match.group(1).strip()
            
            # Look for Method
            if 'Method:' in line and current_entry['method'] is None:
                method_match = re.search(r'Method:\s*(.+)', line)
                if method_match:
                    current_entry['method'] = method_match.group(1).strip()
            
            # Look for Payload JSON (can span multiple lines)
            if 'Payload JSON:' in line:
                json_start = line.find('Payload JSON:')
                json_str = line[json_start + len('Payload JSON:'):].strip()
                
                # If JSON is incomplete, try to read more lines
                if not json_str.startswith('{'):
                    i += 1
                    continue
                
                # Try to parse JSON
                try:
                    current_entry['payload'] = json.loads(json_str)
                except json.JSONDecodeError:
                    # JSON might span multiple lines - collect until we find closing brace
                    json_lines = [json_str]
                    brace_count = json_str.count('{') - json_str.count('}')
                    i += 1
                    while i < len(lines) and brace_count > 0:
                        json_lines.append(lines[i])
                        brace_count += lines[i].count('{') - lines[i].count('}')
                        i += 1
                    try:
                        full_json = '\n'.join(json_lines)
                        current_entry['payload'] = json.loads(full_json)
                    except json.JSONDecodeError:
                        current_entry['payload'] = json_str
            
            # Look for Response Body (can span multiple lines)
            if 'Response Body:' in line:
                json_start = line.find('Response Body:')
                json_str = line[json_start + len('Response Body:'):].strip()
                
                # Try to parse JSON
                try:
                    current_entry['response'] = json.loads(json_str)
                except json.JSONDecodeError:
                    # JSON might span multiple lines
                    json_lines = [json_str]
                    brace_count = json_str.count('{') - json_str.count('}')
                    i += 1
                    while i < len(lines) and brace_count > 0:
                        json_lines.append(lines[i])
                        brace_count += lines[i].count('{') - lines[i].count('}')
                        i += 1
                    try:
                        full_json = '\n'.join(json_lines)
                        current_entry['response'] = json.loads(full_json)
                    except json.JSONDecodeError:
                        current_entry['response'] = json_str
        
        i += 1
    
    return auto_payloads, manual_payloads

def normalize_value(value) -> str:
    """Normalize a value for comparison (convert to string, lowercase if string)"""
    if value is None:
        return "None"
    if isinstance(value, str):
        return value.strip().lower()
    return str(value).strip().lower()

def compare_payloads(auto_payload: Dict, manual_payload: Dict) -> List[Dict]:
    """
    Compare two payloads and return differences.
    
    Returns:
        List of difference dictionaries with keys: field, auto, manual, type_auto, type_manual, severity
    """
    differences = []
    
    if not auto_payload or not manual_payload:
        return [{"field": "payload", "auto": "MISSING" if not auto_payload else "PRESENT", 
                "manual": "MISSING" if not manual_payload else "PRESENT", 
                "severity": "CRITICAL"}]
    
    auto_params = auto_payload.get('payload', {}).get('params', {})
    manual_params = manual_payload.get('payload', {}).get('params', {})
    
    if not auto_params or not manual_params:
        return [{"field": "params", "auto": "MISSING" if not auto_params else "PRESENT",
                "manual": "MISSING" if not manual_params else "PRESENT",
                "severity": "CRITICAL"}]
    
    all_keys = set(auto_params.keys()) | set(manual_params.keys())
    
    for key in sorted(all_keys):
        auto_val = auto_params.get(key)
        manual_val = manual_params.get(key)
        
        # Skip volatile fields
        if key in VOLATILE_FIELDS:
            continue
        
        # Check if field is missing
        if key not in auto_params:
            differences.append({
                'field': key,
                'auto': None,
                'manual': manual_val,
                'type_auto': 'MISSING',
                'type_manual': type(manual_val).__name__,
                'severity': 'HIGH' if key in FORMAT_SENSITIVE_FIELDS else 'MEDIUM'
            })
            continue
        
        if key not in manual_params:
            differences.append({
                'field': key,
                'auto': auto_val,
                'manual': None,
                'type_auto': type(auto_val).__name__,
                'type_manual': 'MISSING',
                'severity': 'HIGH' if key in FORMAT_SENSITIVE_FIELDS else 'MEDIUM'
            })
            continue
        
        # Compare values
        auto_normalized = normalize_value(auto_val)
        manual_normalized = normalize_value(manual_val)
        
        if auto_normalized != manual_normalized:
            severity = 'CRITICAL' if key in FORMAT_SENSITIVE_FIELDS else 'MEDIUM'
            differences.append({
                'field': key,
                'auto': auto_val,
                'manual': manual_val,
                'type_auto': type(auto_val).__name__,
                'type_manual': type(manual_val).__name__,
                'severity': severity
            })
    
    return differences

def save_payloads(auto_payloads: List[Dict], manual_payloads: List[Dict], output_dir: str = "/tmp"):
    """Save payloads to JSON files for inspection"""
    import os
    
    if auto_payloads:
        auto_file = os.path.join(output_dir, "payload_auto.json")
        with open(auto_file, 'w') as f:
            json.dump(auto_payloads[0].get('payload', {}), f, indent=2, ensure_ascii=False)
        print(f"✅ Saved AUTO payload to: {auto_file}")
    
    if manual_payloads:
        manual_file = os.path.join(output_dir, "payload_manual.json")
        with open(manual_file, 'w') as f:
            json.dump(manual_payloads[0].get('payload', {}), f, indent=2, ensure_ascii=False)
        print(f"✅ Saved MANUAL payload to: {manual_file}")

def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: python3 extract_payloads.py <log_file>")
        print("Or pipe logs: docker compose logs backend-aws 2>&1 | python3 extract_payloads.py -")
        sys.exit(1)
    
    if sys.argv[1] == '-':
        log_text = sys.stdin.read()
    else:
        with open(sys.argv[1], 'r') as f:
            log_text = f.read()
    
    auto_payloads, manual_payloads = extract_payloads_from_logs(log_text)
    
    print("="*80)
    print("EXTRACTED PAYLOADS")
    print("="*80)
    print(f"\nAUTO payloads found: {len(auto_payloads)}")
    print(f"MANUAL payloads found: {len(manual_payloads)}")
    
    if not auto_payloads and not manual_payloads:
        print("\n⚠️  No TP_ORDER payloads found in logs.")
        print("   Make sure you're filtering logs correctly:")
        print("   docker compose logs backend-aws 2>&1 | grep 'TP_ORDER' | python3 extract_payloads.py -")
        return
    
    # Save payloads to files
    save_payloads(auto_payloads, manual_payloads)
    
    if auto_payloads:
        print("\n" + "="*80)
        print("AUTO PAYLOAD (First)")
        print("="*80)
        first_auto = auto_payloads[0]
        print(f"Request ID: {first_auto['request_id']}")
        print(f"URL: {first_auto.get('url', 'N/A')}")
        print(f"Method: {first_auto.get('method', 'N/A')}")
        print(f"\nPayload params:")
        params = first_auto.get('payload', {}).get('params', {})
        print(json.dumps(params, indent=2, ensure_ascii=False))
        if first_auto.get('response'):
            print(f"\nResponse:")
            print(json.dumps(first_auto.get('response', {}), indent=2, ensure_ascii=False))
    
    if manual_payloads:
        print("\n" + "="*80)
        print("MANUAL PAYLOAD (First)")
        print("="*80)
        first_manual = manual_payloads[0]
        print(f"Request ID: {first_manual['request_id']}")
        print(f"URL: {first_manual.get('url', 'N/A')}")
        print(f"Method: {first_manual.get('method', 'N/A')}")
        print(f"\nPayload params:")
        params = first_manual.get('payload', {}).get('params', {})
        print(json.dumps(params, indent=2, ensure_ascii=False))
        if first_manual.get('response'):
            print(f"\nResponse:")
            print(json.dumps(first_manual.get('response', {}), indent=2, ensure_ascii=False))
    
    if auto_payloads and manual_payloads:
        print("\n" + "="*80)
        print("COMPARISON")
        print("="*80)
        differences = compare_payloads(auto_payloads[0], manual_payloads[0])
        
        if differences:
            print(f"\n⚠️  Found {len(differences)} differences:")
            
            # Group by severity
            critical = [d for d in differences if d['severity'] == 'CRITICAL']
            high = [d for d in differences if d['severity'] == 'HIGH']
            medium = [d for d in differences if d['severity'] == 'MEDIUM']
            
            if critical:
                print("\n🔴 CRITICAL differences (likely causing errors 229/40004):")
                for diff in critical:
                    print(f"\n  Field: {diff['field']}")
                    print(f"    AUTO:   {diff['auto']} (type: {diff['type_auto']})")
                    print(f"    MANUAL: {diff['manual']} (type: {diff['type_manual']})")
            
            if high:
                print("\n🟠 HIGH priority differences:")
                for diff in high:
                    print(f"\n  Field: {diff['field']}")
                    print(f"    AUTO:   {diff['auto']} (type: {diff['type_auto']})")
                    print(f"    MANUAL: {diff['manual']} (type: {diff['type_manual']})")
            
            if medium:
                print("\n🟡 MEDIUM priority differences (volatile fields):")
                for diff in medium:
                    print(f"\n  Field: {diff['field']}")
                    print(f"    AUTO:   {diff['auto']} (type: {diff['type_auto']})")
                    print(f"    MANUAL: {diff['manual']} (type: {diff['type_manual']})")
            
            print("\n" + "="*80)
            print("RECOMMENDATIONS:")
            print("="*80)
            print("1. Review CRITICAL differences - these are likely causing errors 229/40004")
            print("2. Ensure MANUAL payload matches AUTO payload for all CRITICAL fields")
            print("3. Check Crypto.com API documentation for correct field formats")
            print("="*80)
        else:
            print("\n✅ No differences found! Payloads are identical.")
            print("   If errors persist, check:")
            print("   - Account/position state")
            print("   - Exchange API consistency")
            print("   - Order timing/race conditions")
    
    elif auto_payloads:
        print("\n⚠️  Only AUTO payloads found. Run manual TP creation to compare:")
        print("   docker compose exec backend-aws python3 /app/tests/test_manual_tp.py")
    
    elif manual_payloads:
        print("\n⚠️  Only MANUAL payloads found. Need AUTO payloads for comparison.")
        print("   Wait for automatic TP creation or check logs for [TP_ORDER][AUTO] entries.")
    
    print("\n" + "="*80)

if __name__ == '__main__':
    main()
