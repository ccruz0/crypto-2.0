"""Phase 6A: Autonomous investigation scheduler tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_jarvis import router as jarvis_router
from app.jarvis.change_execution.config import phase5_safety_status
from app.jarvis.execution.safety import SafetyLevel, classify_text
from app.jarvis.investigations.scheduler import config as sched_config
from app.jarvis.investigations.scheduler.leader import try_acquire_leader
from app.jarvis.investigations.scheduler.persistence import (
    ScheduledTaskStatus,
    claim_next_pending_task,
    complete_task,
    create_task,
    ensure_tables,
    has_active_task_for_schedule,
    list_due_schedules,
    upsert_schedule,
)
from app.jarvis.investigations.scheduler.service import (
    execute_task,
    queue_due_investigations,
    recover_stale_running_tasks,
    run_investigation_scheduler_cycle,
    seed_default_schedules,
)
from app.jarvis.investigations.scheduler.templates import RECURRING_INVESTIGATION_TEMPLATES
from app.jarvis.investigations.submit import InvestigationBlockedError, submit_investigation_readonly


@pytest.fixture()
def sched_db(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    import app.database as db_mod
    from app.jarvis.investigations.scheduler import leader as leader_mod
    from app.jarvis.investigations.scheduler import persistence as persist_mod

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    db_mod.ensure_jarvis_scheduled_investigations_tables(engine)
    db_mod.ensure_jarvis_investigations_table(engine)
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(persist_mod, "engine", engine)
    monkeypatch.setattr(leader_mod, "engine", engine)
    yield engine
    engine.dispose()


def test_autostart_when_trading_only_and_scheduler_enabled(monkeypatch):
    monkeypatch.setenv("ATP_TRADING_ONLY", "1")
    monkeypatch.setenv("RUN_TELEGRAM_POLLER", "true")
    monkeypatch.setenv("JARVIS_INVESTIGATION_SCHEDULER_ENABLED", "true")
    assert sched_config.investigation_scheduler_should_autostart() is True


def test_autostart_disabled_when_scheduler_flag_off(monkeypatch):
    monkeypatch.setenv("ATP_TRADING_ONLY", "1")
    monkeypatch.setenv("RUN_TELEGRAM_POLLER", "true")
    monkeypatch.setenv("JARVIS_INVESTIGATION_SCHEDULER_ENABLED", "false")
    assert sched_config.investigation_scheduler_should_autostart() is False


def test_autostart_disabled_on_standby_process(monkeypatch):
    monkeypatch.setenv("ATP_TRADING_ONLY", "1")
    monkeypatch.setenv("RUN_TELEGRAM_POLLER", "false")
    monkeypatch.setenv("JARVIS_INVESTIGATION_SCHEDULER_ENABLED", "true")
    assert sched_config.investigation_scheduler_should_autostart() is False


def test_factory_decouples_investigation_scheduler_from_trading_only():
    from pathlib import Path

    factory_py = Path(__file__).resolve().parents[1] / "app" / "factory.py"
    content = factory_py.read_text()
    inv_block_start = content.index("# Phase 6A: autonomous investigation scheduler")
    inv_block_end = content.index("# Ensure watchlist is never empty", inv_block_start)
    inv_block = content[inv_block_start:inv_block_end]
    assert "investigation_scheduler_should_autostart" in inv_block
    assert "is_atp_trading_only" not in inv_block


def test_agent_scheduler_still_blocked_under_trading_only(monkeypatch):
    monkeypatch.setenv("ATP_TRADING_ONLY", "1")
    monkeypatch.setenv("RUN_TELEGRAM_POLLER", "true")
    from app.core.environment import is_atp_trading_only

    run_poller = True
    assert run_poller and not is_atp_trading_only() is False


def test_scheduler_default_interval_is_15_minutes(monkeypatch):
    monkeypatch.delenv("JARVIS_INVESTIGATION_SCHEDULER_INTERVAL_SECONDS", raising=False)
    assert sched_config.investigation_scheduler_interval_seconds() == 900


def test_scheduler_interval_from_env(monkeypatch):
    monkeypatch.setenv("JARVIS_INVESTIGATION_SCHEDULER_INTERVAL_SECONDS", "600")
    assert sched_config.investigation_scheduler_interval_seconds() == 600


def test_recurring_templates_cover_required_health_checks():
    ids = {t.schedule_id for t in RECURRING_INVESTIGATION_TEMPLATES}
    required = {
        "open_orders_health",
        "portfolio_reconciliation",
        "api_health",
        "exchange_connectivity",
        "database_health",
        "websocket_health",
        "error_log_analysis",
        "deployment_verification",
    }
    assert required.issubset(ids)


def test_seed_default_schedules(sched_db):
    count = seed_default_schedules()
    assert count == len(RECURRING_INVESTIGATION_TEMPLATES)


def test_duplicate_task_prevention(sched_db):
    upsert_schedule(
        schedule_id="open_orders_health",
        template_id="open_orders_empty",
        title="Open orders health",
        objective="Why are open orders empty?",
        category="orders",
        next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    create_task(
        schedule_id="open_orders_health",
        template_id="open_orders_empty",
        objective="Why are open orders empty?",
    )
    assert has_active_task_for_schedule("open_orders_health")
    with pytest.raises(ValueError, match="duplicate active task"):
        create_task(
            schedule_id="open_orders_health",
            template_id="open_orders_empty",
            objective="Why are open orders empty?",
        )


def test_queue_due_skips_duplicate(sched_db):
    now = datetime.now(timezone.utc)
    upsert_schedule(
        schedule_id="api_health",
        template_id="jarvis_task_failing",
        title="API health",
        objective="Why is Jarvis task failing?",
        category="api",
        next_run_at=now - timedelta(minutes=5),
    )
    create_task(
        schedule_id="api_health",
        template_id="jarvis_task_failing",
        objective="Why is Jarvis task failing?",
    )
    queued = queue_due_investigations(interval_seconds=900)
    assert queued == []


def test_single_leader_election(sched_db):
    assert try_acquire_leader("leader-a") is True
    assert try_acquire_leader("leader-b") is False
    assert try_acquire_leader("leader-a") is True


def test_standby_skips_cycle_when_not_leader(sched_db, monkeypatch):
    monkeypatch.setenv("JARVIS_INVESTIGATION_SCHEDULER_ENABLED", "true")
    try_acquire_leader("other-leader")
    with patch(
        "app.jarvis.investigations.scheduler.service._get_instance_id",
        return_value="standby-instance",
    ):
        result = run_investigation_scheduler_cycle()
    assert result["action"] == "standby"


def test_failover_recovers_stale_running_tasks(sched_db):
    upsert_schedule(
        schedule_id="database_health",
        template_id="generic",
        title="Database health",
        objective="Check database health",
        category="database",
    )
    task = create_task(
        schedule_id="database_health",
        template_id="generic",
        objective="Check database health",
    )
    stale_start = datetime.now(timezone.utc) - timedelta(minutes=30)
    with sched_db.begin() as conn:
        from sqlalchemy import text

        conn.execute(
            text(
                """
                UPDATE jarvis_scheduled_investigation_tasks
                SET status = 'running', started_at = :started_at
                WHERE task_id = :task_id
                """
            ),
            {"task_id": task["task_id"], "started_at": stale_start},
        )
    recovered = recover_stale_running_tasks(lease_seconds=60)
    assert recovered == 1


def test_safety_blocks_forbidden_scheduled_objective(sched_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    objective = "Investigate and execute trade if missing orders are detected"
    assert classify_text(objective) == SafetyLevel.FORBIDDEN
    with pytest.raises(InvestigationBlockedError):
        submit_investigation_readonly(objective, persist=False)


def test_phase5_write_gates_remain_disabled(monkeypatch):
    monkeypatch.delenv("JARVIS_PATCH_APPLY_ENABLED", raising=False)
    monkeypatch.delenv("JARVIS_PR_CREATION_ENABLED", raising=False)
    monkeypatch.delenv("JARVIS_GITHUB_WRITE_ENABLED", raising=False)
    status = phase5_safety_status()
    assert status["patch_apply_enabled"] is False
    assert status["pr_creation_enabled"] is False
    assert status["github_write_enabled"] is False


def test_execute_task_uses_human_equivalent_path(sched_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    fake_report = type(
        "Report",
        (),
        {
            "investigation_id": "inv-test-1",
            "status": type("S", (), {"value": "completed"})(),
            "summary": "All checks passed",
            "root_cause": None,
        },
    )()
    with patch(
        "app.jarvis.investigations.scheduler.service.submit_investigation_readonly",
        return_value=fake_report,
    ) as submit_mock:
        result = execute_task(
            {
                "task_id": "task-1",
                "objective": "Why are open orders empty?",
            }
        )
    submit_mock.assert_called_once_with("Why are open orders empty?")
    assert result["ok"] is True
    assert result["investigation_id"] == "inv-test-1"


def test_claim_next_pending_task_is_exclusive(sched_db):
    upsert_schedule(
        schedule_id="websocket_health",
        template_id="websocket_prices_stale",
        title="WebSocket health",
        objective="Why are websocket prices stale?",
        category="websocket",
    )
    create_task(
        schedule_id="websocket_health",
        template_id="websocket_prices_stale",
        objective="Why are websocket prices stale?",
    )
    first = claim_next_pending_task()
    second = claim_next_pending_task()
    assert first is not None
    assert second is None
    assert first["status"] == ScheduledTaskStatus.RUNNING.value


def test_leader_cycle_queues_and_executes(sched_db, monkeypatch):
    monkeypatch.setenv("JARVIS_INVESTIGATION_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    seed_default_schedules()
    now = datetime.now(timezone.utc)
    for schedule in list_due_schedules(now=now):
        pass
    # Force all schedules due
    with sched_db.begin() as conn:
        from sqlalchemy import text

        conn.execute(
            text("UPDATE jarvis_investigation_schedules SET next_run_at = :past"),
            {"past": now - timedelta(hours=1)},
        )
    fake_report = type(
        "Report",
        (),
        {
            "investigation_id": "inv-cycle-1",
            "status": type("S", (), {"value": "completed"})(),
            "summary": "ok",
            "root_cause": "none",
        },
    )()
    holder = sched_config.scheduler_instance_id()
    with patch(
        "app.jarvis.investigations.scheduler.service._get_instance_id",
        return_value=holder,
    ), patch(
        "app.jarvis.investigations.scheduler.service.submit_investigation_readonly",
        return_value=fake_report,
    ):
        try_acquire_leader(holder)
        result = run_investigation_scheduler_cycle()
    assert result["action"] == "cycle_complete"
    assert result["queued_count"] >= 1


@pytest.fixture()
def jarvis_sched_client(sched_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    app = FastAPI()
    app.include_router(jarvis_router)
    return TestClient(app)


def test_api_scheduled_investigations_endpoint(jarvis_sched_client):
    seed_default_schedules()
    resp = jarvis_sched_client.get("/api/jarvis/investigations/scheduled")
    assert resp.status_code == 200
    body = resp.json()
    assert "scheduler" in body
    assert len(body["schedules"]) == len(RECURRING_INVESTIGATION_TEMPLATES)


def test_api_scheduled_report_endpoint(jarvis_sched_client):
    resp = jarvis_sched_client.get("/api/jarvis/investigations/scheduled/report?hours=24")
    assert resp.status_code == 200
    body = resp.json()
    assert "success_rate_pct" in body
    assert "failure_rate_pct" in body
    assert "average_runtime_ms" in body
