"""Tests for render_runtime_env.sh Jarvis Phase 4B/5 flag preservation."""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RENDER_SCRIPT = REPO_ROOT / "scripts" / "aws" / "render_runtime_env.sh"

JARVIS_FLAG_KEYS = (
    "JARVIS_4B_PROPOSALS_ENABLED",
    "JARVIS_4B_MIN_CONFIDENCE",
    "JARVIS_PATCH_APPLY_ENABLED",
    "JARVIS_PR_CREATION_ENABLED",
    "JARVIS_GITHUB_WRITE_ENABLED",
    "JARVIS_REQUIRE_DOUBLE_APPROVAL",
)


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


def test_render_script_declares_jarvis_flag_preservation():
    script_text = RENDER_SCRIPT.read_text(encoding="utf-8")
    for key in (
        "PRESERVE_JARVIS_4B_PROPOSALS_ENABLED",
        "PRESERVE_JARVIS_4B_MIN_CONFIDENCE",
        "PRESERVE_JARVIS_PATCH_APPLY_ENABLED",
        "PRESERVE_JARVIS_PR_CREATION_ENABLED",
        "PRESERVE_JARVIS_GITHUB_WRITE_ENABLED",
        "PRESERVE_JARVIS_REQUIRE_DOUBLE_APPROVAL",
    ):
        assert key in script_text
    assert 'JARVIS_4B_PROPOSALS_ENABLED="${PRESERVE_JARVIS_4B_PROPOSALS_ENABLED:-false}"' in script_text
    assert 'JARVIS_REQUIRE_DOUBLE_APPROVAL="${PRESERVE_JARVIS_REQUIRE_DOUBLE_APPROVAL:-true}"' in script_text


@pytest.mark.parametrize(
    "runtime_env_body,expected",
    [
        (
            textwrap.dedent(
                """\
                TELEGRAM_BOT_TOKEN=old
                TELEGRAM_CHAT_ID=old
                ADMIN_ACTIONS_KEY=old
                JARVIS_4B_PROPOSALS_ENABLED=true
                JARVIS_4B_MIN_CONFIDENCE=75
                """
            ),
            {
                "JARVIS_4B_PROPOSALS_ENABLED": "true",
                "JARVIS_4B_MIN_CONFIDENCE": "75",
                "JARVIS_PATCH_APPLY_ENABLED": "false",
                "JARVIS_PR_CREATION_ENABLED": "false",
                "JARVIS_GITHUB_WRITE_ENABLED": "false",
                "JARVIS_REQUIRE_DOUBLE_APPROVAL": "true",
            },
        ),
        (
            textwrap.dedent(
                """\
                TELEGRAM_BOT_TOKEN=old
                TELEGRAM_CHAT_ID=old
                ADMIN_ACTIONS_KEY=old
                JARVIS_PATCH_APPLY_ENABLED=true
                JARVIS_PR_CREATION_ENABLED=true
                JARVIS_GITHUB_WRITE_ENABLED=true
                JARVIS_REQUIRE_DOUBLE_APPROVAL=false
                """
            ),
            {
                "JARVIS_4B_PROPOSALS_ENABLED": "false",
                "JARVIS_4B_MIN_CONFIDENCE": "50",
                "JARVIS_PATCH_APPLY_ENABLED": "true",
                "JARVIS_PR_CREATION_ENABLED": "true",
                "JARVIS_GITHUB_WRITE_ENABLED": "true",
                "JARVIS_REQUIRE_DOUBLE_APPROVAL": "false",
            },
        ),
        (
            textwrap.dedent(
                """\
                TELEGRAM_BOT_TOKEN=old
                TELEGRAM_CHAT_ID=old
                ADMIN_ACTIONS_KEY=old
                """
            ),
            {
                "JARVIS_4B_PROPOSALS_ENABLED": "false",
                "JARVIS_4B_MIN_CONFIDENCE": "50",
                "JARVIS_PATCH_APPLY_ENABLED": "false",
                "JARVIS_PR_CREATION_ENABLED": "false",
                "JARVIS_GITHUB_WRITE_ENABLED": "false",
                "JARVIS_REQUIRE_DOUBLE_APPROVAL": "true",
            },
        ),
    ],
)
def test_render_jarvis_flags_preserved_or_defaulted(tmp_path: Path, runtime_env_body: str, expected: dict[str, str]):
    result, rendered = _render_in_fixture(tmp_path, runtime_env_body)
    assert result.returncode == 0, result.stderr
    for key, value in expected.items():
        assert rendered[key] == value, f"{key}: expected {value!r}, got {rendered.get(key)!r}"
    assert "JARVIS_4B_SOURCE=preserved" in result.stdout or "JARVIS_4B_SOURCE=default" in result.stdout


def test_render_keeps_phase4b_true_without_enabling_phase5(tmp_path: Path):
    runtime_env_body = textwrap.dedent(
        """\
        TELEGRAM_BOT_TOKEN=old
        TELEGRAM_CHAT_ID=old
        ADMIN_ACTIONS_KEY=old
        JARVIS_4B_PROPOSALS_ENABLED=true
        JARVIS_4B_MIN_CONFIDENCE=50
        """
    )
    result, rendered = _render_in_fixture(tmp_path, runtime_env_body)
    assert result.returncode == 0, result.stderr
    assert rendered["JARVIS_4B_PROPOSALS_ENABLED"] == "true"
    assert rendered["JARVIS_PATCH_APPLY_ENABLED"] == "false"
    assert rendered["JARVIS_PR_CREATION_ENABLED"] == "false"
    assert rendered["JARVIS_GITHUB_WRITE_ENABLED"] == "false"
    assert rendered["JARVIS_REQUIRE_DOUBLE_APPROVAL"] == "true"
    assert "JARVIS_4B_SOURCE=preserved" in result.stdout


def test_render_writes_all_jarvis_flag_keys(tmp_path: Path):
    result, rendered = _render_in_fixture(tmp_path, "TELEGRAM_BOT_TOKEN=old\nTELEGRAM_CHAT_ID=old\nADMIN_ACTIONS_KEY=old\n")
    assert result.returncode == 0, result.stderr
    for key in JARVIS_FLAG_KEYS:
        assert key in rendered
