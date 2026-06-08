#!/usr/bin/env python3
"""
Manual MVP: Bedrock-side staging worker (verify_clone only).

Core logic lives in ``app.jarvis.repo_worker_mvp`` (shared with Jarvis tool ``repo_worker_verify_clone``).

Fail-closed when ATP_TRADING_ONLY=1 unless BEDROCK_REPO_WORKER_ALLOW_IN_TRADING_ONLY=1 (testing only).

Run from repo root (crypto-2.0), with PYTHONPATH including backend:

  cd /path/to/crypto-2.0
  PYTHONPATH=backend python3 backend/scripts/bedrock_repo_worker_mvp.py \\
    --job-file /tmp/verify_job.json \\
    --write-artifact /tmp/bedrock_repo_mvp_out.json

Job file example (verify_clone only):
  {"version": 1, "job_kind": "verify_clone", "correlation_id": "lab-manual-001"}
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from app.jarvis.repo_worker_mvp import (
    assert_not_trading_only_unless_override,
    mvp_result_to_sections,
    run_verify_clone_job,
    validate_mvp_job,
)

logger = logging.getLogger("bedrock_repo_worker_mvp")


def _load_job(arg_json: str | None, arg_file: str | None) -> dict:
    if arg_json and arg_file:
        raise SystemExit("use only one of --job-json or --job-file")
    if arg_json:
        data = json.loads(arg_json)
    elif arg_file:
        p = Path(arg_file)
        if not p.is_file():
            raise SystemExit(f"job file not found: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
    else:
        raise SystemExit("required: --job-json '...' or --job-file path.json")
    return validate_mvp_job(data)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Bedrock repo worker MVP (verify_clone manual scaffold)")
    parser.add_argument("--job-json", help="Inline JSON job payload")
    parser.add_argument("--job-file", help="Path to JSON job file")
    parser.add_argument("--write-artifact", help="Write full JSON artifact to this path")
    parser.add_argument(
        "--keep-staging",
        action="store_true",
        help="Do not remove staging dir after run (debugging)",
    )
    ns = parser.parse_args(argv)

    assert_not_trading_only_unless_override()
    job = _load_job(ns.job_json, ns.job_file)

    artifact = run_verify_clone_job(job, keep_staging=bool(ns.keep_staging))
    artifact["sections"] = mvp_result_to_sections(artifact)

    text = json.dumps(artifact, indent=2, sort_keys=True)
    print(text)

    if ns.write_artifact:
        out_path = Path(ns.write_artifact)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        logger.info("wrote artifact to %s", out_path)

    return 0 if artifact.get("result_status") == "ok" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as e:
        print(f"validation error: {e}", file=sys.stderr)
        raise SystemExit(2) from e
