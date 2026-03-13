"""
ATP instance command execution via AWS SSM.

Allows OpenClaw and agent workflows to run safe, read-only or low-risk
commands on the ATP PROD instance without manual SSH. Uses AWS SSM
send-command; requires AWS credentials and SSM permissions.

Instance: i-087953603011543c5 (atp-rebuild-2026)
Project path: /home/ubuntu/automated-trading-platform
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

_ATP_INSTANCE_ID = "i-087953603011543c5"
_ATP_REGION = "ap-southeast-1"
_ATP_PROJECT_PATH = "/home/ubuntu/automated-trading-platform"

# Allowed subcommand patterns (regex). Applied after stripping "cd ... && " prefix.
_ALLOWED_SUBCOMMANDS = (
    r"^docker\s+compose\s+--profile\s+aws\s+ps\s*$",
    r"^docker\s+compose\s+--profile\s+aws\s+logs\s+--tail=\d+(\s+\w+)?\s*$",
    r"^docker\s+ps\s*$",
    r"^curl\s+-sS(\s+--connect-timeout\s+\d+)?\s+http://127\.0\.0\.1:8002/(ping_fast|api/health)\s*$",
    r"^df\s+-h\s+/\s*$",
    r"^free\s+-h\s*$",
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
    return (os.environ.get("ATP_SSM_INSTANCE_ID") or "").strip() or _ATP_INSTANCE_ID


def _region() -> str:
    return (os.environ.get("ATP_SSM_REGION") or "").strip() or _ATP_REGION


def _project_path() -> str:
    return (os.environ.get("ATP_PROJECT_PATH") or "").strip() or _ATP_PROJECT_PATH


def is_command_allowed(raw_command: str) -> tuple[bool, str]:
    """
    Check if a command is allowed. Returns (allowed, reason).
    Strips "cd /path && " prefix before matching subcommand.
    """
    cmd = (raw_command or "").strip()
    if not cmd:
        return False, "empty command"

    for pat in _DENY_PATTERNS:
        if re.search(pat, cmd, re.IGNORECASE):
            return False, f"denied pattern: {pat}"

    # Extract subcommand (after "cd ... && " if present)
    subcmd = cmd
    if " && " in cmd:
        parts = cmd.split(" && ", 1)
        if len(parts) == 2 and parts[0].strip().startswith("cd "):
            subcmd = parts[1].strip()

    for pat in _ALLOWED_SUBCOMMANDS:
        if re.search(pat, subcmd, re.IGNORECASE):
            return True, "allowed"

    return False, "command not in allowlist"


def run_atp_command(
    command: str,
    *,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """
    Run a command on the ATP instance via AWS SSM.

    Returns:
        {"ok": bool, "stdout": str, "stderr": str, "status": str, "error": str | None}
    """
    allowed, reason = is_command_allowed(command)
    if not allowed:
        logger.warning("atp_ssm_runner: command denied: %s", reason)
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

    # Prepend cd to project if not present
    full_cmd = command
    if "cd " not in command and ("docker" in command or "curl" in command):
        full_cmd = f"cd {proj} && {command}"

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

        # Poll for completion
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
        logger.warning("atp_ssm_runner: SSM failed: %s", e)
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "status": "Error",
            "error": str(e),
        }


def get_atp_instance_info() -> dict[str, Any]:
    """Return ATP instance metadata for prompts and docs."""
    return {
        "instance_id": _instance_id(),
        "region": _region(),
        "project_path": _project_path(),
        "allowed_commands": [
            "docker compose --profile aws ps",
            "docker compose --profile aws logs --tail=50 [service]",
            "curl -sS http://127.0.0.1:8002/ping_fast",
            "curl -sS http://127.0.0.1:8002/api/health",
            "df -h /",
            "free -h",
        ],
    }
