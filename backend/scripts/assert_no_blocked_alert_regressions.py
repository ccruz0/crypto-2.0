#!/usr/bin/env python3
"""
Safety script to check for blocked alert regression patterns.

Usage:
    python3 backend/scripts/assert_no_blocked_alert_regressions.py [log_file]

If no log_file is provided, checks recent Docker logs on AWS.
Exits with non-zero code if any patterns are found.
"""
import sys
import re
import subprocess
import os
from pathlib import Path

# Patterns that indicate blocked alert regression
BLOCKED_PATTERNS = [
    r'send_buy_signal verification',
    r'send_sell_signal verification',
    r'Alerta bloqueada por send_buy_signal verification',
    r'Alerta bloqueada por send_sell_signal verification',
    r'BLOQUEADO.*send_buy_signal',
    r'BLOQUEADO.*send_sell_signal',
    r'BLOCKED.*send_buy_signal',
    r'BLOCKED.*send_sell_signal',
]

def check_file(file_path):
    """Check a log file for blocked alert patterns"""
    matches = []
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line_num, line in enumerate(f, 1):
                for pattern in BLOCKED_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        matches.append({
                            'file': file_path,
                            'line': line_num,
                            'pattern': pattern,
                            'content': line.strip()
                        })
    except FileNotFoundError:
        print(f"Warning: File not found: {file_path}", file=sys.stderr)
    except Exception as e:
        print(f"Error reading {file_path}: {e}", file=sys.stderr)
    
    return matches

def check_docker_logs():
    """Check recent Docker logs on AWS"""
    matches = []
    try:
        cmd = [
            'sh', '-c',
            "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && "
            "bash scripts/aws_backend_logs.sh --tail 10000 2>&1'"
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            for line_num, line in enumerate(result.stdout.split('\n'), 1):
                for pattern in BLOCKED_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        matches.append({
                            'file': 'docker logs (AWS)',
                            'line': line_num,
                            'pattern': pattern,
                            'content': line.strip()
                        })
    except subprocess.TimeoutExpired:
        print("Warning: Timeout checking Docker logs", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Could not check Docker logs: {e}", file=sys.stderr)
    
    return matches

def main():
    """Main entry point"""
    all_matches = []
    
    if len(sys.argv) > 1:
        # Check provided log file(s)
        for log_file in sys.argv[1:]:
            matches = check_file(log_file)
            all_matches.extend(matches)
    else:
        # Check Docker logs on AWS
        print("Checking Docker logs on AWS...")
        matches = check_docker_logs()
        all_matches.extend(matches)
    
    if all_matches:
        print("❌ BLOCKED ALERT REGRESSION DETECTED!", file=sys.stderr)
        print(f"\nFound {len(all_matches)} offending line(s):\n", file=sys.stderr)
        
        for match in all_matches:
            print(
                f"  File: {match['file']}\n"
                f"  Line: {match['line']}\n"
                f"  Pattern: {match['pattern']}\n"
                f"  Content: {match['content'][:200]}\n",
                file=sys.stderr
            )
        
        print(
            "\n⚠️  This indicates alerts are being blocked incorrectly.\n"
            "Portfolio / business rules may block ORDERS, but must NEVER block ALERTS.\n"
            "Check:\n"
            "  - backend/app/services/telegram_notifier.py\n"
            "  - backend/app/services/signal_monitor.py\n"
            "  - docs/BLOCKED_ALERT_REGRESSION_GUARDRAIL.md\n",
            file=sys.stderr
        )
        
        sys.exit(1)
    else:
        print("✅ No blocked alert regression patterns found")
        sys.exit(0)

if __name__ == "__main__":
    main()

