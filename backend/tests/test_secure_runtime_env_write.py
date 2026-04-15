"""Tests for runtime.env merge writes used by Jarvis marketing intake."""

from __future__ import annotations

import os

from app.jarvis.secure_runtime_env_write import persist_env_var_value


def test_persist_mirrors_value_into_os_environ(tmp_path, monkeypatch):
    """Disk write alone is invisible to os.getenv until process env is updated."""
    monkeypatch.delenv("JARVIS_GSC_SITE_URL", raising=False)
    p = tmp_path / "runtime.env"
    p.write_text("OTHER=x\n", encoding="utf-8")
    url = "https://example.com"
    persist_env_var_value("JARVIS_GSC_SITE_URL", url, path=str(p))
    assert os.environ.get("JARVIS_GSC_SITE_URL") == url
    body = p.read_text(encoding="utf-8")
    assert f"JARVIS_GSC_SITE_URL={url}" in body
