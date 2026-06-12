"""Safety hardening tests for Jarvis auto-remediation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.automation.remediation import (  # noqa: E402
    FailureItem,
    filter_false_positive_failures,
    remediate_health_failures,
    should_trigger_remediation,
)
from scripts.automation.remediation_safety import (  # noqa: E402
    ACTION_RESTART_BACKEND,
    SafetyLevel,
    assert_command_safe,
    auto_remediation_dry_run,
    classify_action,
    is_auto_action_allowed,
    log_audit,
    planned_actions_for_health_failures,
)
from scripts.automation.health_check import CheckResult  # noqa: E402


def test_crypto_com_warning_does_not_trigger_remediation(monkeypatch):
    monkeypatch.setenv("ATP_TRADING_ONLY", "1")
    failures = [
        CheckResult(
            "backend_recent_errors",
            False,
            "backend-aws | ERROR API credentials not configured. Cannot get order history.",
        )
    ]
    filtered = filter_false_positive_failures(failures)
    assert filtered == []
    items = [FailureItem.from_check(f) for f in filtered]
    assert should_trigger_remediation(items) is False
    assert planned_actions_for_health_failures(set()) == []


def test_backend_down_plans_safe_restart():
    actions = planned_actions_for_health_failures({"backend_ping_fast"})
    assert ACTION_RESTART_BACKEND in actions
    assert is_auto_action_allowed(ACTION_RESTART_BACKEND)


def test_nginx_change_requires_approval():
    level = classify_action("nginx_change", context="update nginx dashboard.conf proxy_pass")
    assert level == SafetyLevel.NEEDS_APPROVAL


def test_deploy_requires_approval():
    level = classify_action("deploy", context="docker compose up -d --build")
    assert level == SafetyLevel.NEEDS_APPROVAL


def test_trading_action_is_forbidden():
    level = classify_action("execute_trade", context="place_order BTCUSDT market buy")
    assert level == SafetyLevel.FORBIDDEN
    level2 = classify_action("trading_order")
    assert level2 == SafetyLevel.FORBIDDEN


def test_dry_run_performs_no_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_AUTOMATION_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("JARVIS_AUTO_REMEDIATION_DRY_RUN", "true")

    with patch("scripts.automation.remediation.subprocess.run") as mock_run, patch(
        "scripts.automation.remediation._http_post"
    ) as mock_post:
        failures = [FailureItem("backend_ping_fast", "connection refused")]
        actions = remediate_health_failures(failures, dry_run=True)
        mock_run.assert_not_called()
        mock_post.assert_not_called()

    assert actions
    assert all(a.dry_run for a in actions)
    assert all(a.ok for a in actions)


def test_audit_log_is_written(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_AUTOMATION_STATE_DIR", str(tmp_path))

    record = log_audit(
        detected_failure="backend_ping_fast",
        action_attempted="restart_backend",
        result="dry_run_skipped",
        agent_triggered=False,
        approval_required=False,
        dry_run=True,
        detail="test",
        source="unit_test",
    )
    assert record.timestamp
    audit_path = tmp_path / "remediation_audit.jsonl"
    assert audit_path.is_file()
    rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["detected_failure"] == "backend_ping_fast"
    assert rows[0]["action_attempted"] == "restart_backend"
    assert rows[0]["approval_required"] is False
    assert rows[0]["agent_triggered"] is False


def test_destructive_commands_blocked():
    with pytest.raises(ValueError, match="forbidden"):
        assert_command_safe(["docker", "volume", "rm", "postgres_data"])
    with pytest.raises(ValueError, match="forbidden"):
        assert_command_safe(["bash", "-c", "deploy production"])
    with pytest.raises(ValueError):
        assert_command_safe(["docker", "compose", "restart", "db"])


def test_allowlisted_restart_command_passes():
    assert_command_safe(["docker", "compose", "--profile", "aws", "restart", "backend-aws"])


def test_auto_remediation_dry_run_defaults_true(monkeypatch):
    monkeypatch.delenv("JARVIS_AUTO_REMEDIATION_DRY_RUN", raising=False)
    assert auto_remediation_dry_run() is True


def test_jarvis_incident_investigation_only():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routes_monitoring import router as monitoring_router

    app = FastAPI()
    app.include_router(monitoring_router, prefix="/api")
    client = TestClient(app)

    with patch("app.services.notion_tasks.create_incident_task") as mock_create, patch(
        "app.services.notion_tasks.update_notion_task_status"
    ), patch("app.services.agent_scheduler.run_agent_scheduler_cycle") as mock_cycle:
        mock_create.return_value = {"id": "task-inv-1"}
        mock_cycle.return_value = {"ok": True, "action": "investigation_prepared"}

        response = client.post(
            "/api/monitoring/jarvis-incident",
            json={
                "source": "jarvis-health-check",
                "category": "health_check",
                "investigation_only": True,
                "failures": [{"name": "backend_ping_fast", "detail": "down"}],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["investigation_only"] is True
    mock_cycle.assert_called_once()
    assert mock_cycle.call_args.kwargs.get("investigation_only") is True


def test_telegram_message_does_not_leak_secrets(monkeypatch, caplog):
    from scripts.automation.telegram_helper import send_telegram_alert

    monkeypatch.setenv("TELEGRAM_CHAT_ID_OPS", "12345")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "super-secret-token-xyz")
    secret_detail = "EXCHANGE_CUSTOM_API_SECRET=abc123 not configured"
    with caplog.at_level("INFO"):
        send_telegram_alert(f"Health fail: {secret_detail}", dry_run=True)
    combined = caplog.text + secret_detail
    assert "super-secret-token-xyz" not in combined
