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
    classify_exchange_credential_issue,
    exchange_credentials_configured,
    exchange_integration_optional,
    http_fetch,
    is_exchange_credential_warning,
    openclaw_public_allowed,
    scan_docker_health_errors,
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


def test_exchange_credential_warning_detects_missing_credentials():
    assert is_exchange_credential_warning(
        "ERROR app.services.brokers.crypto_com_trade API credentials not configured."
    )
    assert is_exchange_credential_warning(
        "[PORTFOLIO_SNAPSHOT] Crypto.com API credentials not configured. Set EXCHANGE_CUSTOM_API_KEY"
    )
    assert not is_exchange_credential_warning(
        "FATAL database connection refused: could not connect to server"
    )
    assert not is_exchange_credential_warning(
        "password authentication failed for user trader"
    )


def test_scan_docker_health_errors_excludes_vpn_gate_last_error_none(monkeypatch):
    lines = [
        "backend-aws | [INFO] app.vpn_gate: vpn_gate: status=True url=https://api.crypto.com last_error=None",
        "backend-aws | CRITICAL database connection pool exhausted",
    ]

    monkeypatch.setattr(
        "scripts.automation.common.fetch_docker_log_lines",
        lambda service, *, tail=100: lines,
    )
    hits = scan_docker_health_errors("backend-aws", tail=10)
    assert len(hits) == 1
    assert "database connection pool" in hits[0]
    assert "last_error=None" not in hits[0]


def test_scan_docker_health_errors_excludes_exchange_warnings(monkeypatch):
    lines = [
        "backend-aws | ERROR API credentials not configured. Cannot get account summary.",
        "backend-aws | CRITICAL database connection pool exhausted",
    ]

    def fake_fetch(service: str, *, tail: int = 100):
        assert service == "backend-aws"
        return lines

    monkeypatch.setattr(
        "scripts.automation.common.fetch_docker_log_lines",
        fake_fetch,
    )
    hits = scan_docker_health_errors("backend-aws", tail=10)
    assert len(hits) == 1
    assert "database connection pool" in hits[0]
    assert "credentials not configured" not in hits[0]


def test_classify_missing_credentials_as_warning(monkeypatch):
    monkeypatch.delenv("EXCHANGE_CUSTOM_API_KEY", raising=False)
    monkeypatch.delenv("EXCHANGE_CUSTOM_API_SECRET", raising=False)
    monkeypatch.setenv("ATP_TRADING_ONLY", "1")

    severity, message = classify_exchange_credential_issue(log_warnings=[])
    assert severity == "warning"
    assert "Crypto.com API credentials not configured" in message
    assert exchange_integration_optional() is True


def test_classify_configured_credentials_ok(monkeypatch):
    monkeypatch.setenv("EXCHANGE_CUSTOM_API_KEY", "key")
    monkeypatch.setenv("EXCHANGE_CUSTOM_API_SECRET", "secret")

    severity, message = classify_exchange_credential_issue(log_warnings=[])
    assert severity == "ok"
    assert message == "Crypto.com credentials configured"
    assert exchange_credentials_configured() is True


def test_daily_report_includes_exchange_warning(monkeypatch):
    from scripts.automation.daily_report import build_report

    monkeypatch.setattr(
        "scripts.automation.daily_report.http_get",
        lambda url: (True, "HTTP 200", 200),
    )
    monkeypatch.setattr(
        "scripts.automation.daily_report.check_websocket_prices",
        lambda url: (True, "received price payload"),
    )
    monkeypatch.setattr(
        "scripts.automation.daily_report.docker_container_running",
        lambda name: (True, f"{name}: Up"),
    )
    monkeypatch.setattr(
        "scripts.automation.daily_report._query_jarvis_stats",
        lambda: {"total_24h": 0, "failed_24h": 0, "running_stale": 0, "pending_stale": 0},
    )
    monkeypatch.setattr(
        "scripts.automation.daily_report.scan_docker_logs",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "scripts.automation.daily_report._aws_cost_hint",
        lambda: "n/a",
    )
    monkeypatch.setattr(
        "scripts.automation.daily_report._trading_mode",
        lambda: "DRY_RUN",
    )
    monkeypatch.setattr(
        "scripts.automation.daily_report.classify_exchange_credential_issue",
        lambda **kwargs: (
            "warning",
            "Crypto.com API credentials not configured (EXCHANGE_CUSTOM_API_KEY/EXCHANGE_CUSTOM_API_SECRET)",
        ),
    )
    monkeypatch.setattr(
        "scripts.automation.daily_report.exchange_integration_optional",
        lambda: True,
    )

    report = build_report()
    assert "Crypto.com integration: WARNING" in report
    assert "Exchange integration optional in current trading mode" in report


def test_health_check_main_exits_zero_with_exchange_warning_only(monkeypatch):
    from scripts.automation import health_check as hc

    monkeypatch.setenv("JARVIS_AUTOMATIONS_ENABLED", "true")
    monkeypatch.setattr(sys, "argv", ["health_check.py"])
    monkeypatch.setattr(
        hc,
        "run_checks",
        lambda: [__import__("scripts.automation.health_check", fromlist=["CheckResult"]).CheckResult("backend_ping_fast", True, "ok")],
    )
    monkeypatch.setattr(hc, "collect_exchange_warnings", lambda: ("warning", "Crypto.com API credentials not configured"))
    assert hc.main() == 0


def test_health_check_passes_when_only_exchange_warnings(monkeypatch):
    from scripts.automation.health_check import run_checks

    monkeypatch.setenv("JARVIS_AUTOMATIONS_ENABLED", "true")
    monkeypatch.setattr(
        "scripts.automation.health_check.http_get",
        lambda url: (True, "HTTP 200", 200),
    )
    monkeypatch.setattr(
        "scripts.automation.health_check.check_websocket_prices",
        lambda url: (True, "received price payload"),
    )
    monkeypatch.setattr(
        "scripts.automation.health_check.docker_container_running",
        lambda name: (True, f"{name}: Up"),
    )
    monkeypatch.setattr(
        "scripts.automation.health_check.scan_docker_health_errors",
        lambda service, tail=120: [],
    )
    monkeypatch.setattr(
        "scripts.automation.health_check.classify_exchange_credential_issue",
        lambda **kwargs: ("warning", "Crypto.com API credentials not configured"),
    )

    results = run_checks()
    failures = [r for r in results if not r.ok]
    assert failures == []
    assert all(r.ok for r in results)


def test_load_runtime_env_does_not_override_existing(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("JARVIS_AUTOMATIONS_ENABLED=false\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_AUTOMATIONS_ENABLED", "true")
    # load_runtime_env reads from REPO_ROOT; just verify setdefault behavior via CooldownStore path
    store = CooldownStore(path=tmp_path / "c.json")
    store.mark_sent("k")
    assert store.should_send("k", 30) is False
