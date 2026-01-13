#!/usr/bin/env python3
import urllib.request
import json
import sys

diag_key = sys.argv[1] if len(sys.argv) > 1 else ""

url = "http://localhost:8002/api/diagnostics/run-e2e-test?dry_run=true"
req = urllib.request.Request(url, method="POST")
req.add_header("X-Diagnostics-Key", diag_key)

try:
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())
    print(json.dumps(data, indent=2))
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
