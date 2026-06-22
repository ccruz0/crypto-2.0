#!/usr/bin/env python3
"""Bootstrap ACW submit with a real on-disk patch (LAB E2E when Cursor CLI unavailable).

Usage:
  ATP_WORKSPACE_ROOT=/home/ubuntu/crypto-2.0 python3 backend/scripts/diag/acw_lab_submit_patch.py \
    --patch-file logs/acw_e2e/real_patch.diff \
    --objective "Add docs/acw_e2e_validation.md validation marker (LAB E2E)"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend"))

# LAB env overrides (after runtime.env if loaded)
os.environ.setdefault("ATP_WORKSPACE_ROOT", str(REPO))
for key, val in {
    "ATP_TRADING_ONLY": "0",
    "JARVIS_ENABLED": "true",
    "JARVIS_BUILDER_ALLOWED": "1",
    "CURSOR_BRIDGE_ENABLED": "true",
    "JARVIS_PATCH_APPLY_ENABLED": "true",
    "JARVIS_PR_CREATION_ENABLED": "true",
    "JARVIS_GITHUB_WRITE_ENABLED": "true",
}.items():
    os.environ[key] = val

runtime = REPO / "secrets" / "runtime.env"
if runtime.is_file():
    try:
        lines = runtime.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        lines = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def _parse_files(diff: str) -> list[str]:
    files: list[str] = []
    for ln in diff.splitlines():
        if ln.startswith("+++ b/"):
            p = ln[6:].strip()
            if p and p != "/dev/null":
                files.append(p)
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch-file", type=Path, required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    diff = args.patch_file.read_text(encoding="utf-8")
    if not diff.strip():
        print("empty patch file", file=sys.stderr)
        return 1

    from unittest.mock import patch

    from app.jarvis.coding_workflow.service import submit_coding_workflow

    target = _parse_files(diff)
    content_hash = hashlib.sha256(diff.encode()).hexdigest()[:16]
    mock_patch = {
        "patch_id": str(uuid.uuid4()),
        "objective": args.objective,
        "target_files": target,
        "unified_diff": diff,
        "patch_summary": f"LAB real patch: {len(target)} file(s), {len(diff)} bytes",
        "revision": 1,
        "content_hash": content_hash,
        "source": "lab_e2e_real_patch",
        "risk_assessment": {"risk_score": 15, "risk_level": "low", "factors": ["docs_only"]},
        "estimated_impact": {"auto_apply": False, "files_count": len(target)},
    }

    with patch("app.jarvis.coding_workflow.service.generate_patch_via_bridge", return_value=mock_patch):
        detail = submit_coding_workflow(objective=args.objective, target_files=target or None)

    out = args.output or REPO / "logs" / "acw_e2e" / "bootstrap_submit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(detail, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"task_id": detail.get("task_id"), "status": detail.get("status"), "output": str(out)}))
    return 0 if detail.get("status") == "waiting_for_approval" else 1


if __name__ == "__main__":
    sys.exit(main())
