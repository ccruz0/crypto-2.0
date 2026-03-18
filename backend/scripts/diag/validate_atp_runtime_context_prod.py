#!/usr/bin/env python3
"""
Live validation of ATP runtime-context prompt injection on PROD.

Run inside backend-aws container on PROD:
  docker compose --profile aws exec -T backend-aws python scripts/diag/validate_atp_runtime_context_prod.py

Or via SSM: ./scripts/diag/validate_atp_runtime_context_prod_via_ssm.sh

Checks:
- boto3 installed
- AWS credentials available
- _fetch_atp_runtime_context() returns real PROD/LAB data
- build_investigation_prompt includes runtime block
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    out: list[str] = []

    # 1. boto3
    try:
        import boto3
        out.append("BOTO3: installed")
    except ImportError:
        out.append("BOTO3: NOT INSTALLED")
        out.append("GAP: pip install boto3 in backend image")
        _print(out)
        return 1

    # 2. AWS credentials (quick check)
    try:
        sts = boto3.client("sts")
        ident = sts.get_caller_identity()
        out.append(f"AWS_CREDENTIALS: ok (account={ident.get('Account', '?')})")
    except Exception as e:
        out.append(f"AWS_CREDENTIALS: FAILED - {e}")
        out.append("GAP: Instance role or env AWS_* for SSM")
        _print(out)
        return 1

    # 3. _fetch_atp_runtime_context
    try:
        from app.services.openclaw_client import _fetch_atp_runtime_context

        runtime = _fetch_atp_runtime_context()
        if not runtime:
            out.append("RUNTIME_CONTEXT: empty (unexpected)")
        elif "unavailable" in runtime.lower() and "boto3 not installed" in runtime.lower():
            out.append("RUNTIME_CONTEXT: unavailable (boto3) - should not happen after boto3 check")
        elif "unavailable" in runtime.lower():
            out.append("RUNTIME_CONTEXT: partial - some blocks unavailable (SSM/instance?)")
        else:
            out.append("RUNTIME_CONTEXT: real data present")
        out.append("")
        out.append("--- RUNTIME BLOCK (first 1200 chars) ---")
        out.append(runtime[:1200] if runtime else "(empty)")
        out.append("--- END RUNTIME BLOCK ---")
    except Exception as e:
        out.append(f"RUNTIME_CONTEXT: ERROR - {e}")
        import traceback
        out.append(traceback.format_exc())
        _print(out)
        return 1

    # 4. build_investigation_prompt includes runtime
    try:
        from app.services.openclaw_client import build_investigation_prompt

        mock = {
            "task": {
                "id": "val-live",
                "task": "Validate runtime context",
                "details": "docker: Permission denied",
            },
            "repo_area": {"area_name": "backend", "likely_files": [], "relevant_docs": []},
        }
        user_prompt, instructions = build_investigation_prompt(mock)
        has_runtime = "Pre-fetched runtime context" in user_prompt or "ATP PROD" in user_prompt
        has_forbid = "NEVER run docker" in instructions
        out.append("")
        out.append("PROMPT_BUILD: has_runtime=%s has_forbid=%s" % (has_runtime, has_forbid))
        out.append("")
        out.append("--- USER PROMPT (first 800 chars) ---")
        out.append(user_prompt[:800] if user_prompt else "(empty)")
        out.append("--- END PROMPT ---")
    except Exception as e:
        out.append(f"PROMPT_BUILD: ERROR - {e}")
        import traceback
        out.append(traceback.format_exc())
        _print(out)
        return 1

    _print(out)
    return 0


def _print(lines: list[str]) -> None:
    for line in lines:
        print(line)


if __name__ == "__main__":
    sys.exit(main())
