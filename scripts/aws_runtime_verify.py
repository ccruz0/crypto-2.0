#!/usr/bin/env python3
"""
AWS Runtime Verification Script

Verifies production runtime conformity for atp-rebuild-2026 using SSM.
Based on: docs/aws/AWS_ARCHITECTURE.md, AWS_LIVE_AUDIT.md, AWS_REMEDIATION_PLAN.md.

Usage:
  pip install boto3  # if not already installed
  python scripts/aws_runtime_verify.py
  python scripts/aws_runtime_verify.py --json-out /tmp/report.json --history-dir runtime-history
  python scripts/aws_runtime_verify.py --auto-kill  # containment only when CRITICAL (CI: when ALLOW_AUTO_KILL=true)

Exit codes: 0 = Safe, 1 = At Risk, 2 = Critical
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    print("ERROR: boto3 is required. Run: pip install boto3", file=sys.stderr)
    sys.exit(2)

# Defaults (overridable by CLI)
DEFAULT_REGION = "ap-southeast-1"
DEFAULT_INSTANCE_NAME = "atp-rebuild-2026"
DEFAULT_PROJECT_DIR = "/home/ubuntu/automated-trading-platform"
DEFAULT_HISTORY_DIR = "runtime-history"
COMMAND_TIMEOUT_SECONDS = 60
POLL_INTERVAL_SECONDS = 2
REMEDIATION_STDOUT_SNIPPET_MAX = 2000

# Expected app ports (must be 127.0.0.1 or docker, not 0.0.0.0)
EXPECTED_PORTS = {8002, 3000, 5432, 9090, 3001, 9093, 9100, 8080}
# Ports that must NOT be bound to 0.0.0.0 (exposure risk)
CRITICAL_PORTS_NO_PUBLIC = {8002, 3000}

SECTION_MARKER = {
    "DOCKER_PS": "---DOCKER_PS---",
    "DOCKER_COMPOSE_PS": "---DOCKER_COMPOSE_PS---",
    "SS_TULPN": "---SS_TULPN---",
    "SYSTEMCTL": "---SYSTEMCTL---",
    "PS_AUX": "---PS_AUX---",
}


@dataclass
class ValidationResult:
    """Aggregated validation state."""

    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    telegram_poller_count: int = 0
    signal_monitor_count: int = 0
    scheduler_running: bool = False
    ports_public_exposure: List[Tuple[int, str]] = field(default_factory=list)
    unexpected_listeners: List[str] = field(default_factory=list)
    containers_running: List[str] = field(default_factory=list)
    compose_services: List[str] = field(default_factory=list)


def get_instance_id(ec2_client, name_tag: str, region: str) -> Optional[str]:
    """Resolve instance ID from Name tag."""
    try:
        paginator = ec2_client.get_paginator("describe_instances")
        for page in paginator.paginate(
            Filters=[
                {"Name": "instance-state-name", "Values": ["running"]},
                {"Name": "tag:Name", "Values": [name_tag]},
            ]
        ):
            for reservation in page.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    return instance["InstanceId"]
    except (BotoCoreError, ClientError) as e:
        print(f"ERROR: Failed to resolve instance ID: {e}", file=sys.stderr)
    return None


def run_ssm_commands(
    ssm_client, instance_id: str, project_dir: str
) -> Tuple[bool, str, str]:
    """
    Send SSM Run Command with all verification commands; wait for completion.
    Returns (success, stdout, stderr).
    """
    script = f"""
echo '{SECTION_MARKER["DOCKER_PS"]}'
docker ps 2>&1
echo '{SECTION_MARKER["DOCKER_COMPOSE_PS"]}'
cd {project_dir} 2>/dev/null && docker compose --profile aws ps 2>&1 || true
echo '{SECTION_MARKER["SS_TULPN"]}'
ss -tulpn 2>&1
echo '{SECTION_MARKER["SYSTEMCTL"]}'
systemctl list-units --type=service --state=running 2>&1
echo '{SECTION_MARKER["PS_AUX"]}'
ps aux 2>&1 | grep -E 'signal|trade|scheduler|telegram' || true
"""
    try:
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [script.strip()]},
            TimeoutSeconds=COMMAND_TIMEOUT_SECONDS,
        )
        command_id = response["Command"]["CommandId"]
    except (BotoCoreError, ClientError) as e:
        print(f"ERROR: SSM send_command failed: {e}", file=sys.stderr)
        return False, "", str(e)

    deadline = time.time() + COMMAND_TIMEOUT_SECONDS
    while time.time() < deadline:
        try:
            inv = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id,
            )
        except (BotoCoreError, ClientError) as e:
            print(f"ERROR: get_command_invocation failed: {e}", file=sys.stderr)
            return False, "", str(e)

        status = inv.get("Status", "")
        status_details = inv.get("StatusDetails", "")
        if status == "Success":
            return True, inv.get("StandardOutputContent", ""), inv.get("StandardErrorContent", "")
        if status in ("Failed", "Cancelled", "TimedOut") or "Undeliverable" in (status_details or ""):
            err = status_details or inv.get("StandardErrorContent", "") or status
            if "Undeliverable" in (status_details or ""):
                err = "Undeliverable (SSM agent unreachable or ConnectionLost)"
            return False, inv.get("StandardOutputContent", ""), err

        time.sleep(POLL_INTERVAL_SECONDS)

    return False, "", "Timeout waiting for command completion"


def run_containment_command(
    ssm_client, instance_id: str, project_dir: str, region: str
) -> Tuple[Optional[str], bool, str]:
    """
    Send SSM containment command (docker compose stop, pkill telegram). Best-effort.
    Returns (command_id, success, stdout_snippet).
    """
    script = """
set -euo pipefail
echo "=== AUTO_KILL ==="
cd "${ATP_DIR:-/home/ubuntu/automated-trading-platform}" || cd /opt/automated-trading-platform || true
if command -v docker >/dev/null 2>&1; then
  docker ps 2>&1 || true
  docker compose --profile aws stop 2>&1 || true
  docker compose --profile aws ps 2>&1 || true
else
  echo "docker not available"
fi
pkill -f 'telegram' 2>/dev/null || true
echo "AUTO_KILL_DONE"
"""
    try:
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [script.strip()]},
            TimeoutSeconds=COMMAND_TIMEOUT_SECONDS,
        )
        command_id = response["Command"]["CommandId"]
    except (BotoCoreError, ClientError) as e:
        return None, False, str(e)[:REMEDIATION_STDOUT_SNIPPET_MAX]

    deadline = time.time() + COMMAND_TIMEOUT_SECONDS
    while time.time() < deadline:
        try:
            inv = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id,
            )
        except (BotoCoreError, ClientError):
            return command_id, False, "(get_command_invocation failed)"

        status = inv.get("Status", "")
        if status == "Success":
            out = inv.get("StandardOutputContent", "") or ""
            return command_id, True, out[:REMEDIATION_STDOUT_SNIPPET_MAX]
        if status in ("Failed", "Cancelled", "TimedOut"):
            out = inv.get("StandardOutputContent", "") or inv.get("StatusDetails", "") or status
            return command_id, False, out[:REMEDIATION_STDOUT_SNIPPET_MAX]

        time.sleep(POLL_INTERVAL_SECONDS)

    return command_id, False, "Timeout waiting for containment command"


def parse_section(raw: str, marker: str) -> str:
    """Extract content between marker and next marker or end."""
    start = raw.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    end = len(raw)
    for m in SECTION_MARKER.values():
        if m == marker:
            continue
        idx = raw.find(m, start)
        if idx != -1 and idx < end:
            end = idx
    return raw[start:end].strip()


def parse_and_validate(stdout: str, stderr: str) -> ValidationResult:
    """Parse command output and run validation rules."""
    result = ValidationResult()
    full = stdout + "\n" + stderr

    # Containers
    docker_ps = parse_section(full, SECTION_MARKER["DOCKER_PS"])
    for line in docker_ps.splitlines():
        if line.strip() and "CONTAINER" not in line:
            parts = line.split()
            if len(parts) >= 2:
                result.containers_running.append(parts[-1] if parts[-1].startswith("atp-") or "backend" in line or "frontend" in line or "postgres" in line else parts[1])

    compose_ps = parse_section(full, SECTION_MARKER["DOCKER_COMPOSE_PS"])
    for line in compose_ps.splitlines():
        if "NAME" in line.upper() and "backend" in line.lower():
            continue
        if line.strip() and ("backend" in line or "frontend" in line or "market" in line or "db" in line or "prometheus" in line or "grafana" in line):
            result.compose_services.append(line.strip())

    # Ports: parse ss -tulpn
    ss_out = parse_section(full, SECTION_MARKER["SS_TULPN"])
    for line in ss_out.splitlines():
        if "LISTEN" not in line:
            continue
        match = re.search(r"(\d+\.\d+\.\d+\.\d+|\*|::):(\d+)", line)
        if match:
            addr, port_str = match.group(1), match.group(2)
            try:
                port = int(port_str)
            except ValueError:
                continue
            if addr == "0.0.0.0" and port in CRITICAL_PORTS_NO_PUBLIC:
                result.ports_public_exposure.append((port, line.strip()))
            if addr == "0.0.0.0" and port not in EXPECTED_PORTS and port > 1024:
                result.unexpected_listeners.append(f"port {port} on 0.0.0.0: {line.strip()[:80]}")

    # Processes: telegram poller, signal monitor, scheduler
    ps_out = parse_section(full, SECTION_MARKER["PS_AUX"])
    for line in ps_out.splitlines():
        if not line.strip():
            continue
        lower = line.lower()
        if "telegram" in lower or "long.poll" in lower or "getupdates" in lower:
            result.telegram_poller_count += 1
        if "signal" in lower and ("monitor" in lower or "signal_monitor" in lower):
            result.signal_monitor_count += 1
        if "scheduler" in lower or "market.updater" in lower or "run_updater" in lower:
            result.scheduler_running = True
        if "gunicorn" in lower and "backend" in lower:
            result.scheduler_running = True

    # Validation rules
    if result.telegram_poller_count == 0:
        result.warnings.append("No Telegram poller process detected (expected exactly one).")
    elif result.telegram_poller_count > 1:
        result.errors.append(f"Duplicate Telegram pollers detected: count={result.telegram_poller_count} (expected 1).")

    if not result.scheduler_running and not result.containers_running:
        result.warnings.append("No trading/scheduler process or containers detected; stack may be down.")
    elif not result.scheduler_running:
        result.warnings.append("No explicit scheduler/market-updater process found in process list.")

    if result.signal_monitor_count > 1:
        result.errors.append(f"Duplicate signal monitor processes: count={result.signal_monitor_count} (expected 0 or 1).")

    if result.ports_public_exposure:
        result.errors.append(
            f"Critical ports bound to 0.0.0.0 (exposure risk): {[p for p, _ in result.ports_public_exposure]}"
        )

    if result.unexpected_listeners:
        result.warnings.append(f"Unexpected listeners on 0.0.0.0: {result.unexpected_listeners[:3]}")

    return result


def classify(result: ValidationResult, ssm_reachable: bool) -> str:
    """Return PRODUCTION_SAFE | PRODUCTION_AT_RISK | CRITICAL_RUNTIME_VIOLATION."""
    if not ssm_reachable:
        return "CRITICAL_RUNTIME_VIOLATION"
    if result.errors:
        return "CRITICAL_RUNTIME_VIOLATION"
    if result.warnings or result.ports_public_exposure:
        return "PRODUCTION_AT_RISK"
    return "PRODUCTION_SAFE"


def exit_code(classification: str) -> int:
    if classification == "PRODUCTION_SAFE":
        return 0
    if classification == "PRODUCTION_AT_RISK":
        return 1
    return 2


def build_report(
    instance_name: str,
    instance_id: Optional[str],
    region: str,
    ssm_ok: bool,
    stdout: str,
    stderr: str,
    result: ValidationResult,
    classification: str,
    remediation: Dict[str, Any],
) -> Dict[str, Any]:
    """Build structured report dict for JSON output."""
    telegram_poller_ok = result.telegram_poller_count == 1
    exposed_ports_ok = len(result.ports_public_exposure) == 0
    exposed_ports_notes = []
    if result.ports_public_exposure:
        exposed_ports_notes = [f"port {p} on 0.0.0.0" for p, _ in result.ports_public_exposure]

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "region": region,
        "instance_name": instance_name,
        "instance_id": instance_id,
        "ssm_status": "ok" if ssm_ok else "failed",
        "containers": result.containers_running,
        "processes": {
            "telegram_poller_count": result.telegram_poller_count,
            "signal_monitor_count": result.signal_monitor_count,
            "scheduler_running": result.scheduler_running,
        },
        "ports": {
            "public_exposure": [p for p, _ in result.ports_public_exposure],
            "unexpected_listeners": result.unexpected_listeners[:10],
        },
        "checks": {
            "telegram_pollers_found": result.telegram_poller_count,
            "telegram_poller_ok": telegram_poller_ok,
            "scheduler_ok": result.scheduler_running,
            "signal_monitor_ok": result.signal_monitor_count <= 1,
            "exposed_ports_ok": exposed_ports_ok,
            "exposed_ports_notes": exposed_ports_notes,
        },
        "classification": classification,
        "remediation": remediation,
    }
    return report


def write_history(report: Dict[str, Any], history_dir: str) -> None:
    """Write dated copy to history_dir/YYYY-MM-DD/production-HHMMSS-<classification>.json. Best-effort."""
    try:
        ts = report.get("timestamp_utc", "")
        if ts:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d")
            time_str = dt.strftime("%H%M%S")
        else:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            time_str = datetime.now(timezone.utc).strftime("%H%M%S")
        classification = report.get("classification", "UNKNOWN").replace(" ", "_")
        dir_path = os.path.join(history_dir, date_str)
        os.makedirs(dir_path, exist_ok=True)
        path = os.path.join(dir_path, f"production-{time_str}-{classification}.json")
        with open(path, "w") as f:
            json.dump(report, f, indent=2)
    except Exception:
        pass  # best-effort; do not change exit code


def print_report(
    instance_name: str,
    instance_id: Optional[str],
    region: str,
    ssm_ok: bool,
    stdout: str,
    stderr: str,
    result: ValidationResult,
    classification: str,
) -> None:
    """Print human-readable report to stdout."""
    print("\n" + "=" * 60)
    print("AWS RUNTIME VERIFICATION REPORT")
    print("=" * 60)
    print(f"Target instance: {instance_name} ({instance_id or 'N/A'})")
    print(f"Region: {region}")
    print()

    print("--- Section: SSM Connectivity ---")
    if ssm_ok:
        print("Status: SSM command delivered and completed successfully.")
    else:
        print("Status: FAILED (ConnectionLost, Undeliverable, or command error).")
        if stderr:
            print(f"Stderr: {stderr[:500]}")
    print()

    if not ssm_ok:
        print("--- Section: Containers ---")
        print("(Not available: SSM unreachable)")
        print()
        print("--- Section: Processes ---")
        print("(Not available: SSM unreachable)")
        print()
        print("--- Section: Ports ---")
        print("(Not available: SSM unreachable)")
        print()
        print("--- Section: Telegram Poller Status ---")
        print("(Not available: SSM unreachable)")
    else:
        print("--- Section: Containers ---")
        if result.containers_running:
            for c in result.containers_running[:20]:
                print(f"  {c}")
            if len(result.containers_running) > 20:
                print(f"  ... and {len(result.containers_running) - 20} more")
        else:
            print("  (No container names parsed from docker ps)")
        if result.compose_services:
            print("Compose services (sample):")
            for s in result.compose_services[:15]:
                print(f"  {s[:70]}")
        print()

        print("--- Section: Processes ---")
        print(f"Telegram poller count: {result.telegram_poller_count}")
        print(f"Signal monitor count: {result.signal_monitor_count}")
        print(f"Scheduler/trading process detected: {result.scheduler_running}")
        if result.errors:
            print("Errors:")
            for e in result.errors:
                print(f"  - {e}")
        if result.warnings:
            print("Warnings:")
            for w in result.warnings:
                print(f"  - {w}")
        print()

        print("--- Section: Ports ---")
        if result.ports_public_exposure:
            print("CRITICAL - Ports bound to 0.0.0.0:")
            for port, line in result.ports_public_exposure:
                print(f"  {port}: {line[:60]}")
        else:
            print("No critical ports bound to 0.0.0.0 (OK).")
        if result.unexpected_listeners:
            print("Unexpected listeners:")
            for u in result.unexpected_listeners[:5]:
                print(f"  {u}")
        print()

        print("--- Section: Telegram Poller Status ---")
        if result.telegram_poller_count == 1:
            print("OK: Exactly one Telegram poller process detected.")
        elif result.telegram_poller_count == 0:
            print("WARNING: No Telegram poller process detected.")
        else:
            print(f"CRITICAL: Duplicate Telegram pollers: {result.telegram_poller_count} (expected 1).")
    print()

    print("--- Section: Risk Classification ---")
    print(classification)
    print()
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="AWS runtime verification (SSM)")
    parser.add_argument("--auto-kill", action="store_true", help="Run containment when CRITICAL (CI only when ALLOW_AUTO_KILL=true)")
    parser.add_argument("--instance-name", default=DEFAULT_INSTANCE_NAME, help=f"Instance Name tag (default: {DEFAULT_INSTANCE_NAME})")
    parser.add_argument("--region", default=DEFAULT_REGION, help=f"Region (default: {DEFAULT_REGION})")
    parser.add_argument("--json-out", default=None, help="Write JSON report to this path")
    parser.add_argument("--history-dir", default=DEFAULT_HISTORY_DIR, help=f"Write history copies here (default: {DEFAULT_HISTORY_DIR})")
    args = parser.parse_args()

    region = args.region
    instance_name = args.instance_name
    project_dir = os.environ.get("ATP_DIR", DEFAULT_PROJECT_DIR)

    ec2 = boto3.client("ec2", region_name=region)
    ssm = boto3.client("ssm", region_name=region)

    instance_id = get_instance_id(ec2, instance_name, region)
    if not instance_id:
        print("ERROR: Could not resolve instance ID for tag Name=" + instance_name, file=sys.stderr)
        report = build_report(
            instance_name, None, region, False, "", "Instance not found or not running",
            ValidationResult(), "CRITICAL_RUNTIME_VIOLATION",
            {"attempted": False, "allowed": False, "ssm_command_id": None, "status": "skipped", "stdout_snippet": ""},
        )
        print_report(instance_name, None, region, False, "", "Instance not found", ValidationResult(), "CRITICAL_RUNTIME_VIOLATION")
        if args.json_out:
            try:
                with open(args.json_out, "w") as f:
                    json.dump(report, f, indent=2)
            except Exception:
                pass
        if args.history_dir:
            write_history(report, args.history_dir)
        return 2

    ssm_ok, stdout, stderr = run_ssm_commands(ssm, instance_id, project_dir)
    if not ssm_ok:
        report = build_report(
            instance_name, instance_id, region, False, stdout, stderr,
            ValidationResult(), "CRITICAL_RUNTIME_VIOLATION",
            {"attempted": False, "allowed": False, "ssm_command_id": None, "status": "skipped", "stdout_snippet": stderr[:REMEDIATION_STDOUT_SNIPPET_MAX]},
        )
        print_report(instance_name, instance_id, region, False, stdout, stderr, ValidationResult(), "CRITICAL_RUNTIME_VIOLATION")
        if args.json_out:
            try:
                with open(args.json_out, "w") as f:
                    json.dump(report, f, indent=2)
            except Exception:
                pass
        if args.auto_kill:
            remediation = {"attempted": True, "allowed": True, "ssm_command_id": None, "status": "pending", "stdout_snippet": ""}
            cmd_id, success, snippet = run_containment_command(ssm, instance_id, project_dir, region)
            remediation["ssm_command_id"] = cmd_id
            remediation["status"] = "ok" if success else "failed"
            remediation["stdout_snippet"] = snippet
            report["remediation"] = remediation
            if args.json_out:
                try:
                    with open(args.json_out, "w") as f:
                        json.dump(report, f, indent=2)
                except Exception:
                    pass
        if args.history_dir:
            write_history(report, args.history_dir)
        return 2

    result = parse_and_validate(stdout, stderr)
    classification = classify(result, ssm_reachable=True)
    remediation = {"attempted": False, "allowed": args.auto_kill, "ssm_command_id": None, "status": "skipped", "stdout_snippet": ""}

    if classification == "CRITICAL_RUNTIME_VIOLATION" and args.auto_kill:
        remediation["attempted"] = True
        remediation["allowed"] = True
        cmd_id, success, snippet = run_containment_command(ssm, instance_id, project_dir, region)
        remediation["ssm_command_id"] = cmd_id
        remediation["status"] = "ok" if success else "failed"
        remediation["stdout_snippet"] = snippet

    report = build_report(instance_name, instance_id, region, ssm_ok, stdout, stderr, result, classification, remediation)
    print_report(instance_name, instance_id, region, ssm_ok, stdout, stderr, result, classification)

    if args.json_out:
        try:
            with open(args.json_out, "w") as f:
                json.dump(report, f, indent=2)
        except Exception:
            pass
    if args.history_dir:
        write_history(report, args.history_dir)

    return exit_code(classification)


if __name__ == "__main__":
    sys.exit(main())
