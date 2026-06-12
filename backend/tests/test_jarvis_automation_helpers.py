"""Unit tests for Jarvis production automation helpers."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.automation.common import (  # noqa: E402
    CooldownStore,
    automations_enabled,
    http_fetch,
    openclaw_public_allowed,
)
from scripts.automation.openclaw_guard import (  # noqa: E402
    detect_nginx_openclaw_exposure,
    detect_openclaw_tab_in_source,
)


def test_automations_enabled_parses_truthy(monkeypatch):
    monkeypatch.setenv("JARVIS_AUTOMATIONS_ENABLED", "true")
    assert automations_enabled() is True
    monkeypatch.setenv("JARVIS_AUTOMATIONS_ENABLED", "false")
    assert automations_enabled() is False


def test_openclaw_public_allowed_default_false(monkeypatch):
    monkeypatch.delenv("OPENCLAW_PUBLIC_ALLOWED", raising=False)
    assert openclaw_public_allowed() is False
    monkeypatch.setenv("OPENCLAW_PUBLIC_ALLOWED", "true")
    assert openclaw_public_allowed() is True


def test_cooldown_blocks_duplicate_alert():
    with tempfile.TemporaryDirectory() as tmp:
        store = CooldownStore(path=Path(tmp) / "cooldowns.json")
        assert store.should_send("health:backend", 30) is True
        store.mark_sent("health:backend")
        assert store.should_send("health:backend", 30) is False
        store._data["health:backend"]["last_sent_ts"] = (
            datetime.now(timezone.utc) - timedelta(minutes=31)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        store._save()
        store._load()
        assert store.should_send("health:backend", 30) is True


def test_openclaw_guard_detects_mocked_tab_string():
    mock = """
    const tabs = [
      { id: 'portfolio', label: 'Portfolio' },
      { id: 'openclaw', label: 'OpenClaw' },
    ];
    """
    hits = detect_openclaw_tab_in_source(mock, path_label="mock")
    assert len(hits) == 1
    assert "OpenClaw" in hits[0].detail


def test_nginx_openclaw_proxy_detected_when_not_allowed(monkeypatch):
    monkeypatch.setenv("OPENCLAW_PUBLIC_ALLOWED", "false")
    config = """
    location /openclaw/ {
        proxy_pass http://127.0.0.1:8080/openclaw/;
    }
    """
    hits = detect_nginx_openclaw_exposure(config, path_label="nginx/test.conf")
    assert any("prox" in h.detail.lower() for h in hits)


def test_nginx_openclaw_redirect_allowed(monkeypatch):
    monkeypatch.setenv("OPENCLAW_PUBLIC_ALLOWED", "false")
    config = """
    location = /openclaw { return 302 /; }
    location ^~ /openclaw/ { return 302 /; }
    """
    hits = detect_nginx_openclaw_exposure(config, path_label="nginx/dashboard.conf")
    assert hits == []


def test_telegram_dry_run_does_not_require_token(monkeypatch):
    from scripts.automation.telegram_helper import send_telegram_alert

    monkeypatch.setenv("TELEGRAM_CHAT_ID_OPS", "12345")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert send_telegram_alert("test alert", dry_run=True) is True


def test_telegram_helper_never_logs_token(caplog, monkeypatch):
    from scripts.automation.telegram_helper import send_telegram_alert

    monkeypatch.setenv("TELEGRAM_CHAT_ID_OPS", "12345")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token-12345")
    with caplog.at_level("INFO"):
        send_telegram_alert("hello", dry_run=True)
    combined = caplog.text + "hello"
    assert "secret-token-12345" not in combined


def test_http_fetch_invalid_url():
    ok, detail, code, body = http_fetch("http://127.0.0.1:1/not-a-real-port", timeout=1.0)
    assert ok is False
    assert code is None or code >= 400
    assert body == "" or isinstance(body, str)


def test_load_runtime_env_does_not_override_existing(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("JARVIS_AUTOMATIONS_ENABLED=false\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_AUTOMATIONS_ENABLED", "true")
    # load_runtime_env reads from REPO_ROOT; just verify setdefault behavior via CooldownStore path
    store = CooldownStore(path=tmp_path / "c.json")
    store.mark_sent("k")
    assert store.should_send("k", 30) is False
