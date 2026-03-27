"""
LAB instance command execution via AWS SSM.

Allows OpenClaw (running on LAB) to run safe commands on the LAB host
for self-diagnostics: docker ps, docker logs openclaw, etc.
Uses AWS SSM send-command; requires AWS credentials and SSM permissions.

Instance: i-0d82c172235770a0d (atp-lab-ssm-clean)
Project path: /home/ubuntu/crypto-2.0
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

_LAB_INSTANCE_ID = "i-0d82c172235770a0d"
_LAB_REGION = "ap-southeast-1"
_LAB_PROJECT_PATH = "/home/ubuntu/crypto-2.0"

# Allowed subcommand patterns for LAB (OpenClaw self-diagnostics).
_ALLOWED_SUBCOMMANDS = (
    r"^docker\s+ps\s*$",
    r"^docker\s+logs\s+openclaw\s+--tail=\d+\s*$",
    r"^docker\s+inspect\s+openclaw\s*$",
    r"^docker\s+compose\s+-f\s+docker-compose\.openclaw\.yml\s+ps\s*$",
    r"^docker\s+compose\s+-f\s+docker-compose\.openclaw\.yml\s+logs\s+--tail=\d+(\s+\w+)?\s*$",
    r"^whoami\s*$",
    r"^id\s*$",
    r"^ls\s+-la\s+/var/log/openclaw(\s+.*)?\s*$",
    r"^cat\s+/var/log/openclaw/\S+\s*$",
    r"^tail\s+-\d+\s+/var/log/openclaw/\S+\s*$",
    r"^test\s+-r\s+/var/log/openclaw\s*$",
)
_DENY_PATTERNS = (
    r"rm\s+-rf",
    r"sudo\s+",
    r">\s*/",
    r"git\s+push",
    r"docker\s+compose\s+down",
    r"docker\s+compose\s+up\s+-d",
    r"systemctl\s+",
    r"reboot",
    r"shutdown",
)


def _instance_id() -> str:
    return (os.environ.get("LAB_SSM_INSTANCE_ID") or "").strip() or _LAB_INSTANCE_ID


def _region() -> str:
    return (os.environ.get("LAB_SSM_REGION") or "").strip() or _LAB_REGION


def _project_path() -> str:
    return (os.environ.get("LAB_PROJECT_PATH") or "").strip() or _LAB_PROJECT_PATH


def is_command_allowed(raw_command: str) -> tuple[bool, str]:
    """Check if a command is allowed. Returns (allowed, reason)."""
    cmd = (raw_command or "").strip()
    if not cmd:
        return False, "empty command"

    for pat in _DENY_PATTERNS:
        if re.search(pat, cmd, re.IGNORECASE):
            return False, f"denied pattern: {pat}"

    subcmd = cmd
    if " && " in cmd:
        parts = cmd.split(" && ", 1)
        if len(parts) == 2 and parts[0].strip().startswith("cd "):
            subcmd = parts[1].strip()

    for pat in _ALLOWED_SUBCOMMANDS:
        if re.search(pat, subcmd, re.IGNORECASE):
            return True, "allowed"

    return False, "command not in allowlist"


def run_lab_command(
    command: str,
    *,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """
    Run a command on the LAB instance via AWS SSM.

    Returns:
        {"ok": bool, "stdout": str, "stderr": str, "status": str, "error": str | None}
    """
    allowed, reason = is_command_allowed(command)
    if not allowed:
        logger.warning("lab_ssm_runner: command denied: %s", reason)
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "status": "Denied",
            "error": f"Command not allowed: {reason}",
        }

    try:
        import boto3
    except ImportError:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "status": "Error",
            "error": "boto3 not installed",
        }

    instance = _instance_id()
    region = _region()
    proj = _project_path()

    full_cmd = command
    if "cd " not in command and ("docker" in command or "ls" in command or "cat" in command):
        full_cmd = f"cd {proj} 2>/dev/null || true && {command}"

    commands = ["set -e", full_cmd]

    try:
        client = boto3.client("ssm", region_name=region)
        resp = client.send_command(
            InstanceIds=[instance],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": commands},
            TimeoutSeconds=min(timeout_seconds, 120),
        )
        cmd_id = resp.get("Command", {}).get("CommandId")
        if not cmd_id:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "",
                "status": "Error",
                "error": "No CommandId in SSM response",
            }

        for _ in range(max(1, timeout_seconds // 2)):
            time.sleep(2)
            inv = client.get_command_invocation(
                CommandId=cmd_id,
                InstanceId=instance,
            )
            status = (inv.get("Status") or "").strip()
            if status in ("Success", "Failed", "Cancelled", "TimedOut"):
                return {
                    "ok": status == "Success",
                    "stdout": (inv.get("StandardOutputContent") or "").strip(),
                    "stderr": (inv.get("StandardErrorContent") or "").strip(),
                    "status": status,
                    "error": inv.get("StandardErrorContent", "").strip() if status != "Success" else None,
                }

        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "status": "TimedOut",
            "error": f"Command {cmd_id} did not complete within {timeout_seconds}s",
        }
    except Exception as e:
        logger.warning("lab_ssm_runner: SSM failed: %s", e)
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "status": "Error",
            "error": str(e),
        }


def get_lab_instance_info() -> dict[str, Any]:
    """Return LAB instance metadata for prompts and docs."""
    return {
        "instance_id": _instance_id(),
        "region": _region(),
        "project_path": _project_path(),
        "allowed_commands": [
            "docker ps",
            "docker logs openclaw --tail=100",
            "docker inspect openclaw",
            "docker compose -f docker-compose.openclaw.yml ps",
            "docker compose -f docker-compose.openclaw.yml logs --tail=50 openclaw",
            "whoami",
            "ls -la /var/log/openclaw",
        ],
        "log_path_note": "OpenClaw logs: use 'docker logs openclaw --tail=N' via run-lab-command. Inside container: /var/log/openclaw/ (directory, not /var/log/openclaw.log).",
    }
