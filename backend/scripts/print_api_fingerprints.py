#!/usr/bin/env python3
"""
Print API fingerprint headers for verification.
Tries localhost:8002 first, then falls back to BASE_URL env var.
"""

import sys
import os
import requests
from urllib.parse import urlparse

def main():
    # Try localhost first (for AWS host or local Docker)
    api_url = os.getenv("API_URL", "http://localhost:8002/api/dashboard")
    if not api_url.endswith("/api/dashboard"):
        api_url = f"{api_url.rstrip('/')}/api/dashboard"
    
    print(f"Checking: {api_url}")
    print("=" * 70)
    
    try:
        # Use HEAD request for speed (should return same headers as GET)
        response = requests.head(api_url, timeout=5, allow_redirects=True)
        
        # If HEAD doesn't work, try GET
        if response.status_code >= 400:
            response = requests.get(api_url, timeout=5, allow_redirects=True)
        
        print(f"Status: {response.status_code}")
        print("")
        
        # Extract fingerprint headers
        headers = {
            "X-ATP-Backend-Commit": response.headers.get("X-ATP-Backend-Commit", "MISSING"),
            "X-ATP-Backend-BuildTime": response.headers.get("X-ATP-Backend-BuildTime", "MISSING"),
            "X-ATP-DB-Host": response.headers.get("X-ATP-DB-Host", "MISSING"),
            "X-ATP-DB-Name": response.headers.get("X-ATP-DB-Name", "MISSING"),
            "X-ATP-DB-Hash": response.headers.get("X-ATP-DB-Hash", "MISSING"),
        }
        
        all_present = all(v != "MISSING" for v in headers.values())
        
        print("Fingerprint Headers:")
        for key, value in headers.items():
            status = "✓" if value != "MISSING" else "✗"
            print(f"  {status} {key}: {value}")
        
        print("")
        if all_present:
            print("✅ PASS: All fingerprint headers present")
            return 0
        else:
            print("❌ FAIL: Some fingerprint headers missing")
            return 1
            
    except requests.exceptions.ConnectionError:
        print("❌ FAIL: Could not connect to API")
        print("")
        print("Possible causes:")
        print("  - Backend not running")
        print("  - Wrong host/port")
        print("  - Firewall blocking connection")
        print("")
        print("If running on Mac, you may need to:")
        print("  - SSH to AWS: ssh hilovivo-aws 'curl -sI http://localhost:8002/api/dashboard'")
        print("  - Or use wrapper: backend/scripts/run_in_backend_container.sh python3 scripts/print_api_fingerprints.py")
        return 1
    except Exception as e:
        print(f"❌ FAIL: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())

