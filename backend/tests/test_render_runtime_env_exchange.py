"""Tests for render_runtime_env.sh exchange credential preservation."""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RENDER_SCRIPT = REPO_ROOT / "scripts" / "aws" / "render_runtime_env.sh"


def test_render_script_declares_ssm_exchange_paths():
    script_text = RENDER_SCRIPT.read_text(encoding="utf-8")
    assert "SSM_EXCHANGE_API_KEY=\"/automated-trading-platform/prod/exchange_custom/api_key\"" in script_text
    assert "SSM_EXCHANGE_API_SECRET=\"/automated-trading-platform/prod/exchange_custom/api_secret\"" in script_text
    assert "EXCHANGE_CREDS_SOURCE" in script_text
    assert "PRESERVE_EXCHANGE_API_KEY" in script_text


def test_render_preserves_exchange_credentials_when_ssm_missing():
    """Integration: render must keep existing EXCHANGE_CUSTOM_* lines when SSM has none."""
    backup = REPO_ROOT / "secrets" / "runtime.env"
    if not backup.exists():
        return
    before = subprocess.run(
        ["sudo", "grep", "-E", "^EXCHANGE_CUSTOM_API_(KEY|SECRET)=", str(backup)],
        capture_output=True,
        text=True,
    )
    if before.returncode != 0:
        return  # no exchange creds to preserve in this environment

    result = subprocess.run(
        ["sudo", "bash", str(RENDER_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    after = subprocess.run(
        ["sudo", "grep", "-E", "^EXCHANGE_CUSTOM_API_(KEY|SECRET)=", str(backup)],
        capture_output=True,
        text=True,
    )
    assert after.returncode == 0
    assert before.stdout.strip() == after.stdout.strip()
    assert "EXCHANGE_CUSTOM_SOURCE=preserved" in result.stdout or "EXCHANGE_CUSTOM=YES" in result.stdout
