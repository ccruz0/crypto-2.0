#!/usr/bin/env python3
"""Verify PROD runtime safety for AWS Runtime Guard / Sentinel CI workflows.

Modes (``AWS_RUNTIME_VERIFY_MODE`` or ``--mode``):
  sentinel   - Full guard: repo compose ports + runtime checks (default on push)
  prod-check - Read-only JARVIS-style prod check: EC2/SSM/runtime only (scheduled)

Exit codes:
  0 - PRODUCTION_SAFE
  1 - PRODUCTION_AT_RISK (non-blocking warnings; sentinel mode only)
  2 - CRITICAL_RUNTIME_VIOLATION (blocks deployment / fails scheduled check)

Writes runtime-report.json and appends to runtime-history/.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROD_INSTANCE_ID = os.environ.get("AWS_PROD_INSTANCE_ID", "i-087953603011543c5")
AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
API_BASE = os.environ.get("ATP_API_BASE", "https://dashboard.hilovivo.com")
DISK_ALERT_PCT = int(os.environ.get("AWS_RUNTIME_DISK_ALERT_PCT", "80"))
REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
REPORT_PATH = REPO_ROOT / "runtime-report.json"
HISTORY_DIR = REPO_ROOT / "runtime-history"


def _remote_check_script(mode: str) -> str:
    health_violation = mode == "prod-check"
    health_fail_block = (
        '  echo "SCHEDULER_OK=FAIL http=$HTTP_CODE"\n'
        "  VIOLATIONS=$((VIOLATIONS + 1))"
        if health_violation
        else '  echo "SCHEDULER_OK=WARN http=$HTTP_CODE"\n  WARNINGS=$((WARNINGS + 1))'
    )
    return rf"""bash <<'REMOTE_EOF'
set -euo pipefail
cd /home/ubuntu/crypto-2.0 2>/dev/null || cd /home/ubuntu/automated-trading-platform || exit 3
VIOLATIONS=0
WARNINGS=0

# backend-aws container must be running (exclude canary)
BACKEND_AWS_LINE="$(docker ps --format '{{{{.Names}}}} {{{{.Status}}}}' 2>/dev/null | grep 'backend-aws' | grep -v canary | head -1 || true)"
if echo "$BACKEND_AWS_LINE" | grep -qiE '(^| )Up|running'; then
  echo "BACKEND_AWS=OK line=$BACKEND_AWS_LINE"
else
  echo "BACKEND_AWS=FAIL line=${{BACKEND_AWS_LINE:-none}}"
  VIOLATIONS=$((VIOLATIONS + 1))
fi

# Root disk usage
DISK_PCT="$(df -P / | awk 'NR==2 {{gsub("%","",$5); print $5}}')"
DISK_PCT="${{DISK_PCT//[^0-9]/}}"
[[ -z "$DISK_PCT" ]] && DISK_PCT=100
if [ "$DISK_PCT" -gt {DISK_ALERT_PCT} ]; then
  echo "DISK_USAGE=FAIL pct=$DISK_PCT threshold={DISK_ALERT_PCT}"
  VIOLATIONS=$((VIOLATIONS + 1))
else
  echo "DISK_USAGE=OK pct=$DISK_PCT threshold={DISK_ALERT_PCT}"
fi

# Port exposure: backend/frontend must bind localhost only
PORT_OUT="$(ss -ltnp 2>/dev/null | grep -E '(:8002|:3000)' || true)"
if echo "$PORT_OUT" | grep -qE '0\.0\.0\.0:(8002|3000)(\s|$)'; then
  echo "EXPOSED_PORTS=FAIL"
  VIOLATIONS=$((VIOLATIONS + 1))
elif echo "$PORT_OUT" | grep -q '127.0.0.1:8002' && echo "$PORT_OUT" | grep -q '127.0.0.1:3000'; then
  echo "EXPOSED_PORTS=OK"
else
  echo "EXPOSED_PORTS=WARN"
  WARNINGS=$((WARNINGS + 1))
fi

# Duplicate Telegram pollers: only primary backend-aws should poll (not canary or market-updater)
POLLER_COUNT=0
for c in $(docker ps --format '{{{{.Names}}}}' 2>/dev/null | grep 'backend-aws' | grep -v canary || true); do
  val="$(docker exec "$c" printenv RUN_TELEGRAM_POLLER 2>/dev/null || echo true)"
  case "${{val,,}}" in
    true|1|yes) POLLER_COUNT=$((POLLER_COUNT + 1)) ;;
  esac
done
if [ "$POLLER_COUNT" -gt 1 ]; then
  echo "TELEGRAM_POLLER=FAIL count=$POLLER_COUNT"
  VIOLATIONS=$((VIOLATIONS + 1))
elif [ "$POLLER_COUNT" -eq 0 ]; then
  echo "TELEGRAM_POLLER=WARN count=0"
  WARNINGS=$((WARNINGS + 1))
else
  echo "TELEGRAM_POLLER=OK count=$POLLER_COUNT"
fi

# Scheduler / backend health
HTTP_CODE="$(curl -sS -o /dev/null -w '%{{http_code}}' --connect-timeout 5 --max-time 15 http://127.0.0.1:8002/api/health 2>/dev/null || echo 000)"
if [ "$HTTP_CODE" = "200" ]; then
  echo "SCHEDULER_OK=OK http=$HTTP_CODE"
else
{health_fail_block}
fi

echo "VIOLATIONS=$VIOLATIONS"
echo "WARNINGS=$WARNINGS"
if [ "$VIOLATIONS" -gt 0 ]; then exit 2; fi
exit 0
REMOTE_EOF
"""


def _verification_mode() -> str:
    raw = os.environ.get("AWS_RUNTIME_VERIFY_MODE", "sentinel").strip().lower()
    if raw in {"prod-check", "prod_check", "prodcheck"}:
        return "prod-check"
    return "sentinel"


def _quiet_success() -> bool:
    return os.environ.get("AWS_RUNTIME_VERIFY_QUIET", "").strip().lower() in {"1", "true", "yes"}


def _curl_health(url: str, timeout: int = 10) -> tuple[int, str]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, "ok"
    except urllib.error.HTTPError as exc:
        return exc.code, str(exc)
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def _compose_ports_ok() -> bool:
    if not COMPOSE_FILE.is_file():
        return False
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    if re.search(r'"0\.0\.0\.0:8002"|"0\.0\.0\.0:3000"', text):
        return False
    return "127.0.0.1:8002:8002" in text and "127.0.0.1:3000:3000" in text


def _ec2_instance_state() -> tuple[str, str]:
    try:
        import boto3
    except ImportError:
        return "failed", "boto3 not installed"
    client = boto3.client("ec2", region_name=AWS_REGION)
    try:
        resp = client.describe_instances(InstanceIds=[PROD_INSTANCE_ID])
        reservations = resp.get("Reservations") or []
        if not reservations or not reservations[0].get("Instances"):
            return "failed", "instance not found"
        state = reservations[0]["Instances"][0].get("State", {}).get("Name", "unknown")
        if state == "running":
            return "ok", state
        return "failed", state
    except Exception as exc:  # noqa: BLE001
        return "failed", str(exc)


def _ssm_ping_status() -> tuple[str, str]:
    try:
        import boto3
    except ImportError:
        return "failed", "boto3 not installed"
    client = boto3.client("ssm", region_name=AWS_REGION)
    try:
        resp = client.describe_instance_information(
            Filters=[{"Key": "InstanceIds", "Values": [PROD_INSTANCE_ID]}]
        )
        items = resp.get("InstanceInformationList") or []
        if not items:
            return "failed", "instance not registered in SSM"
        status = items[0].get("PingStatus") or "Unknown"
        if status == "Online":
            return "ok", status
        return "failed", status
    except Exception as exc:  # noqa: BLE001
        return "failed", str(exc)


def _run_ssm_remote_check(mode: str) -> tuple[int, str, str]:
    try:
        import boto3
    except ImportError:
        return 2, "", "boto3 not installed"

    client = boto3.client("ssm", region_name=AWS_REGION)
    remote_check = _remote_check_script(mode)
    try:
        send = client.send_command(
            InstanceIds=[PROD_INSTANCE_ID],
            DocumentName="AWS-RunShellScript",
            Comment=f"aws_runtime_verify {mode} {datetime.now(timezone.utc).isoformat()}",
            Parameters={"commands": [remote_check]},
            TimeoutSeconds=120,
        )
        command_id = send["Command"]["CommandId"]
    except Exception as exc:  # noqa: BLE001
        return 2, "", f"send_command failed: {exc}"

    deadline = time.time() + 120
    while time.time() < deadline:
        time.sleep(3)
        try:
            inv = client.get_command_invocation(
                CommandId=command_id,
                InstanceId=PROD_INSTANCE_ID,
            )
        except client.exceptions.InvocationDoesNotExist:
            continue
        status = inv.get("Status", "")
        if status in {"Success", "Failed", "Cancelled", "TimedOut"}:
            stdout = inv.get("StandardOutputContent") or ""
            stderr = inv.get("StandardErrorContent") or ""
            code = inv.get("ResponseCode")
            if code is None or code == -1:
                code = 2 if status != "Success" else 0
            return int(code), stdout, stderr
    return 2, "", "SSM command timed out"


def _parse_remote(stdout: str) -> dict[str, str]:
    checks: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" in line:
            key, _, val = line.partition("=")
            checks[key.strip().lower()] = val.strip()
    return checks


def _check_ok(parsed: dict[str, str], key: str) -> bool:
    return parsed.get(key, "").startswith("OK")


def _disk_pct(parsed: dict[str, str]) -> int | None:
    raw = parsed.get("disk_usage", "")
    match = re.search(r"pct=(\d+)", raw)
    if match:
        return int(match.group(1))
    return None


def _classification(exit_code: int) -> str:
    if exit_code == 0:
        return "PRODUCTION_SAFE"
    if exit_code == 2:
        return "CRITICAL_RUNTIME_VIOLATION"
    return "PRODUCTION_AT_RISK"


def _write_report(report: dict) -> None:
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    hist = HISTORY_DIR / f"{stamp}-{report['classification']}.json"
    hist.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _emit(exit_code: int, report: dict, remote_stdout: str = "", remote_stderr: str = "") -> int:
    quiet = _quiet_success() and exit_code == 0
    if not quiet:
        print(f"classification={report['classification']}")
        print(f"Recorded exitcode={exit_code} to GITHUB_OUTPUT ({report['classification']})")
        next_step = (report.get("remediation") or {}).get("next_step") or ""
        if next_step:
            print(f"next_step={next_step}")
        checks = report.get("checks") or {}
        if checks:
            print("checks=" + json.dumps(checks, sort_keys=True))
        ssm_details = report.get("ssm_status_details") or ""
        if ssm_details:
            print(f"ssm_status={report.get('ssm_status')} details={ssm_details}")
        if remote_stdout.strip():
            print(remote_stdout.strip())
        if remote_stderr.strip():
            print(remote_stderr.strip(), file=sys.stderr)
    return exit_code


def _fail_report(
    report: dict,
    *,
    classification: str,
    exit_code: int,
    next_step: str,
    remote_stdout: str = "",
    remote_stderr: str = "",
) -> int:
    report["classification"] = classification
    report["remediation"]["next_step"] = next_step
    _write_report(report)
    return _emit(exit_code, report, remote_stdout, remote_stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify PROD AWS runtime safety")
    parser.add_argument(
        "--mode",
        choices=("sentinel", "prod-check"),
        help="Verification mode (overrides AWS_RUNTIME_VERIFY_MODE)",
    )
    args = parser.parse_args(argv)
    mode = args.mode or _verification_mode()
    prod_check = mode == "prod-check"

    report: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "instance_id": PROD_INSTANCE_ID,
        "region": AWS_REGION,
        "checks": {},
        "ssm_status": "failed",
        "ssm_status_details": "",
        "remediation": {
            "attempted": False,
            "status": "skipped",
            "next_step": "",
        },
    }

    ec2_status, ec2_details = _ec2_instance_state()
    report["checks"]["ec2_instance_running"] = ec2_status == "ok"
    report["checks"]["ec2_instance_state"] = ec2_details
    ec2_denied = "AccessDenied" in str(ec2_details) or "UnauthorizedOperation" in str(ec2_details)
    if ec2_status != "ok" and not ec2_denied:
        report["ssm_status"] = "skipped"
        report["ssm_status_details"] = f"EC2 state={ec2_details}"
        return _fail_report(
            report,
            classification="CRITICAL_RUNTIME_VIOLATION",
            exit_code=2,
            next_step=(
                f"Start or restore EC2 instance atp-rebuild-2026 ({PROD_INSTANCE_ID}). "
                f"Current state: {ec2_details}"
            ),
        )
    if ec2_denied:
        # OIDC deploy role historically lacked ec2:DescribeInstances; SSM Online is enough.
        report["checks"]["ec2_instance_running"] = None
        report["checks"]["ec2_describe_skipped"] = True

    if not prod_check:
        compose_ok = _compose_ports_ok()
        report["checks"]["compose_ports_ok"] = compose_ok
        if not compose_ok:
            report["ssm_status"] = "skipped"
            report["ssm_status_details"] = (
                "docker-compose.yml exposes 0.0.0.0 or missing localhost bindings"
            )
            return _fail_report(
                report,
                classification="CRITICAL_RUNTIME_VIOLATION",
                exit_code=2,
                next_step=(
                    "Fix docker-compose.yml to use 127.0.0.1:8002:8002 and 127.0.0.1:3000:3000"
                ),
            )

    health_url = f"{API_BASE.rstrip('/')}/api/health"
    http_code, _health_detail = _curl_health(health_url)
    report["checks"]["public_api_http"] = http_code
    public_api_ok = http_code == 200
    report["checks"]["public_api_ok"] = public_api_ok

    ssm_status, ssm_details = _ssm_ping_status()
    report["ssm_status"] = ssm_status
    report["ssm_status_details"] = ssm_details

    if ssm_status != "ok":
        report["checks"]["telegram_poller_ok"] = False
        report["checks"]["scheduler_ok"] = False
        report["checks"]["exposed_ports_ok"] = False
        report["checks"]["backend_aws_ok"] = False
        report["checks"]["disk_usage_ok"] = False
        return _fail_report(
            report,
            classification="CRITICAL_RUNTIME_VIOLATION",
            exit_code=2,
            next_step=(
                f"Restore SSM connectivity for atp-rebuild-2026 ({PROD_INSTANCE_ID}) "
                f"then re-run verification. Details: {ssm_details}"
            ),
        )

    remote_code, remote_stdout, remote_stderr = _run_ssm_remote_check(mode)
    parsed = _parse_remote(remote_stdout)
    report["checks"]["backend_aws_ok"] = _check_ok(parsed, "backend_aws")
    report["checks"]["disk_usage_ok"] = _check_ok(parsed, "disk_usage")
    disk_pct = _disk_pct(parsed)
    if disk_pct is not None:
        report["checks"]["disk_usage_pct"] = disk_pct
        report["checks"]["disk_alert_threshold_pct"] = DISK_ALERT_PCT
    report["checks"]["telegram_poller_ok"] = _check_ok(parsed, "telegram_poller")
    report["checks"]["exposed_ports_ok"] = _check_ok(parsed, "exposed_ports")
    report["checks"]["scheduler_ok"] = _check_ok(parsed, "scheduler_ok")
    report["remote_stdout"] = remote_stdout.strip()
    if remote_stderr.strip():
        report["remote_stderr"] = remote_stderr.strip()

    exit_code = 2 if remote_code == 2 else 0
    runtime_warnings = any(
        not report["checks"].get(k, True)
        for k in ("telegram_poller_ok", "exposed_ports_ok", "scheduler_ok")
        if k in report["checks"] and not report["checks"][k]
    )
    has_warnings = (
        remote_code == 1
        or (not public_api_ok and not prod_check)
        or runtime_warnings
    )
    if prod_check and not public_api_ok:
        exit_code = 2
        has_warnings = True
    if has_warnings and exit_code == 0 and not prod_check:
        report["classification"] = "PRODUCTION_AT_RISK"
        exit_code = 1
    else:
        report["classification"] = _classification(exit_code)

    if exit_code == 2:
        report["remediation"]["next_step"] = (
            "Resolve runtime violations on PROD (instance/SSM, disk, backend-aws, "
            "duplicate pollers, port exposure, or health). See remote_stdout in runtime-report.json."
        )
    elif exit_code == 1:
        report["remediation"]["next_step"] = (
            "Review warnings (public API or backend health). Re-run after remediation."
        )

    _write_report(report)
    return _emit(exit_code, report, remote_stdout, remote_stderr)


if __name__ == "__main__":
    raise SystemExit(main())
