"""Tests for render_runtime_env.sh brief + Telethon user-API preservation."""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RENDER_SCRIPT = REPO_ROOT / "scripts" / "aws" / "render_runtime_env.sh"


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _render_in_fixture(tmp_path: Path, runtime_env_body: str) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    fixture_root = tmp_path / "fixture"
    scripts_dir = fixture_root / "scripts" / "aws"
    secrets_dir = fixture_root / "secrets"
    bin_dir = fixture_root / "bin"
    scripts_dir.mkdir(parents=True)
    secrets_dir.mkdir(parents=True)
    bin_dir.mkdir(parents=True)

    # Force fallback to .env.aws (avoid slow SSM calls in CI/dev).
    (bin_dir / "aws").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    (bin_dir / "aws").chmod(0o755)

    (fixture_root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (fixture_root / ".env.aws").write_text(
        textwrap.dedent(
            """\
            TELEGRAM_BOT_TOKEN=test-bot-token
            TELEGRAM_CHAT_ID=12345
            ADMIN_ACTIONS_KEY=test-admin-key
            DIAGNOSTICS_API_KEY=test-diag-key
            """
        ),
        encoding="utf-8",
    )
    (secrets_dir / "runtime.env").write_text(runtime_env_body, encoding="utf-8")
    shutil.copy2(RENDER_SCRIPT, scripts_dir / "render_runtime_env.sh")

    env = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    result = subprocess.run(
        ["bash", str(scripts_dir / "render_runtime_env.sh")],
        cwd=str(fixture_root),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    rendered = _parse_env_file(secrets_dir / "runtime.env")
    return result, rendered


def test_render_script_declares_brief_ssm_and_preserve():
    script_text = RENDER_SCRIPT.read_text(encoding="utf-8")
    assert 'SSM_BRIEF_API_KEY="/automated-trading-platform/prod/brief/api_key"' in script_text
    assert 'SSM_TELEGRAM_API_ID="/automated-trading-platform/prod/telegram/api_id"' in script_text
    assert 'SSM_TELEGRAM_API_HASH="/automated-trading-platform/prod/telegram/api_hash"' in script_text
    for key in (
        "PRESERVE_BRIEF_API_KEY",
        "PRESERVE_BRIEF_MAILBOXES_PATH",
        "PRESERVE_BRIEF_RATE_LIMIT_PER_MINUTE",
        "PRESERVE_BRIEF_ICS_URLS",
        "PRESERVE_TELEGRAM_API_ID",
        "PRESERVE_TELEGRAM_API_HASH",
        "PRESERVE_TELEGRAM_SESSION_PATH",
        "BRIEF_SOURCE",
        "TELEGRAM_USER_API_SOURCE",
    ):
        assert key in script_text


def test_render_preserves_brief_and_telegram_user_api(tmp_path: Path):
    result, rendered = _render_in_fixture(
        tmp_path,
        textwrap.dedent(
            """\
            TELEGRAM_BOT_TOKEN=old
            TELEGRAM_CHAT_ID=old
            ADMIN_ACTIONS_KEY=old
            BRIEF_API_KEY=preserved-brief-key-64chars-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
            BRIEF_MAILBOXES_PATH=/app/secrets/brief_mailboxes.json
            BRIEF_RATE_LIMIT_PER_MINUTE=30
            BRIEF_ICS_URLS=https://example.test/cal.ics
            TELEGRAM_API_ID=12345678
            TELEGRAM_API_HASH=abcdef0123456789abcdef0123456789
            TELEGRAM_SESSION_PATH=/data/telegram/hilovivo.session
            """
        ),
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert rendered["BRIEF_API_KEY"].startswith("preserved-brief-key")
    assert rendered["BRIEF_MAILBOXES_PATH"] == "/app/secrets/brief_mailboxes.json"
    assert rendered["BRIEF_RATE_LIMIT_PER_MINUTE"] == "30"
    assert rendered["BRIEF_ICS_URLS"] == "https://example.test/cal.ics"
    assert rendered["TELEGRAM_API_ID"] == "12345678"
    assert rendered["TELEGRAM_API_HASH"] == "abcdef0123456789abcdef0123456789"
    assert rendered["TELEGRAM_SESSION_PATH"] == "/data/telegram/hilovivo.session"
    assert "BRIEF_SOURCE=preserved" in result.stdout
    assert "TELEGRAM_USER_API_SOURCE=preserved" in result.stdout
    assert "BRIEF_API_KEY=YES" in result.stdout
    assert "TELEGRAM_USER_API=YES" in result.stdout


def test_render_applies_brief_path_defaults_when_absent(tmp_path: Path):
    result, rendered = _render_in_fixture(
        tmp_path,
        textwrap.dedent(
            """\
            TELEGRAM_BOT_TOKEN=old
            TELEGRAM_CHAT_ID=old
            ADMIN_ACTIONS_KEY=old
            """
        ),
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert "BRIEF_API_KEY" not in rendered
    assert rendered["BRIEF_MAILBOXES_PATH"] == "/app/secrets/brief_mailboxes.json"
    assert rendered["BRIEF_RATE_LIMIT_PER_MINUTE"] == "30"
    assert rendered["TELEGRAM_SESSION_PATH"] == "/data/telegram/hilovivo.session"
    assert "BRIEF_API_KEY=NO" in result.stdout
    assert "TELEGRAM_USER_API=NO" in result.stdout


def test_render_reads_brief_from_env_aws_when_not_preserved(tmp_path: Path):
    fixture_root = tmp_path / "fixture"
    scripts_dir = fixture_root / "scripts" / "aws"
    secrets_dir = fixture_root / "secrets"
    bin_dir = fixture_root / "bin"
    scripts_dir.mkdir(parents=True)
    secrets_dir.mkdir(parents=True)
    bin_dir.mkdir(parents=True)
    (bin_dir / "aws").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    (bin_dir / "aws").chmod(0o755)
    (fixture_root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (fixture_root / ".env.aws").write_text(
        textwrap.dedent(
            """\
            TELEGRAM_BOT_TOKEN=test-bot-token
            TELEGRAM_CHAT_ID=12345
            ADMIN_ACTIONS_KEY=test-admin-key
            DIAGNOSTICS_API_KEY=test-diag-key
            BRIEF_API_KEY=from-env-aws-brief-key
            TELEGRAM_API_ID=87654321
            TELEGRAM_API_HASH=hashfromenvaws0123456789abcdef01
            """
        ),
        encoding="utf-8",
    )
    (secrets_dir / "runtime.env").write_text(
        "TELEGRAM_BOT_TOKEN=old\nTELEGRAM_CHAT_ID=old\nADMIN_ACTIONS_KEY=old\n",
        encoding="utf-8",
    )
    shutil.copy2(RENDER_SCRIPT, scripts_dir / "render_runtime_env.sh")
    result = subprocess.run(
        ["bash", str(scripts_dir / "render_runtime_env.sh")],
        cwd=str(fixture_root),
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
    )
    rendered = _parse_env_file(secrets_dir / "runtime.env")
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert rendered["BRIEF_API_KEY"] == "from-env-aws-brief-key"
    assert rendered["TELEGRAM_API_ID"] == "87654321"
    assert rendered["TELEGRAM_API_HASH"] == "hashfromenvaws0123456789abcdef01"
    assert "BRIEF_SOURCE=env.aws" in result.stdout
    assert "TELEGRAM_USER_API_SOURCE=env.aws" in result.stdout
