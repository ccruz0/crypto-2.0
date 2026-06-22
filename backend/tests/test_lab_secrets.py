"""Tests for LAB secret loading."""

from __future__ import annotations

import os
from pathlib import Path

from app.core.lab_secrets import load_lab_runtime_env


def test_load_lab_runtime_env_lab_overrides_runtime(tmp_path, monkeypatch):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "runtime.env").write_text(
        "ATP_TRADING_ONLY=1\nCURSOR_BRIDGE_ENABLED=false\nEXECUTION_CONTEXT=AWS\n",
        encoding="utf-8",
    )
    (secrets / "runtime.env.lab").write_text(
        "ATP_TRADING_ONLY=0\nCURSOR_BRIDGE_ENABLED=true\nEXECUTION_CONTEXT=LAB\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ATP_TRADING_ONLY", raising=False)
    monkeypatch.delenv("CURSOR_BRIDGE_ENABLED", raising=False)
    monkeypatch.delenv("EXECUTION_CONTEXT", raising=False)

    loaded = load_lab_runtime_env(repo_root=tmp_path)

    assert loaded == ["runtime.env", "runtime.env.lab"]
    assert os.environ["ATP_TRADING_ONLY"] == "0"
    assert os.environ["CURSOR_BRIDGE_ENABLED"] == "true"
    assert os.environ["EXECUTION_CONTEXT"] == "LAB"
