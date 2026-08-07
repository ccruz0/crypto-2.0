"""Settings must not raise when secrets/runtime.env is unreadable (appuser vs umask 077)."""

import os
from pathlib import Path

from app.core.config import load_settings, readable_env_files


def test_readable_env_files_skips_unreadable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    runtime = secrets / "runtime.env"
    runtime.write_text("RUN_TELEGRAM=true\n", encoding="utf-8")
    os.chmod(runtime, 0o000)

    readable = readable_env_files((".env", "backend/.env", "secrets/runtime.env"))
    assert "secrets/runtime.env" not in readable

    # Restore so cleanup can delete
    os.chmod(runtime, 0o600)


def test_load_settings_survives_unreadable_runtime_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    runtime = secrets / "runtime.env"
    runtime.write_text("TELEGRAM_BOT_TOKEN_AWS=should-not-load\n", encoding="utf-8")
    os.chmod(runtime, 0o000)

    monkeypatch.setenv("RUN_TELEGRAM", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_AWS", "from-process-env")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_AWS", "-1001")

    settings = load_settings()
    assert settings.TELEGRAM_BOT_TOKEN_AWS == "from-process-env"
    assert settings.RUN_TELEGRAM == "true"

    os.chmod(runtime, 0o600)
