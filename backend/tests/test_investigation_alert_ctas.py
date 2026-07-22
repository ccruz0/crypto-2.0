"""Tests for Jarvis investigation alert Telegram CTAs (view / create task / snooze)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.jarvis.investigations.alerting.fingerprint import build_fingerprint
from app.jarvis.investigations.alerting.persistence import (
    alert_is_snoozed,
    snooze_alert,
    upsert_alert,
)
from app.jarvis.investigations.alerting.telegram import (
    format_investigation_alert_message,
    should_send_telegram,
)
from app.jarvis.investigations.alerting.telegram_inline import (
    _parse_alert_callback,
    handle_jarvis_investigation_alert_callback,
)
from app.jarvis.investigations.alerting.telegram_markup import (
    build_investigation_alert_inline_markup,
)
from app.jarvis.investigations.alerting.types import AlertInput, AlertRecord, AlertSeverity, AlertStatus


@pytest.fixture()
def alert_db(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    import app.database as db_mod
    from app.jarvis.investigations.alerting import persistence as alert_persist_mod

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    db_mod.ensure_jarvis_alerting_tables(engine)
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(alert_persist_mod, "engine", engine)
    yield engine
    engine.dispose()


def _alert_record(**kwargs) -> AlertRecord:
    defaults = dict(
        alert_id="alert-abcdef123456",
        created_at="2026-07-22T08:00:00+00:00",
        severity="CRITICAL",
        source="dashboard_exchange_mismatch",
        investigation_id="inv-1",
        title="Why does dashboard differ from exchange?",
        summary="Exchange 59 vs DB 79",
        evidence=[{"detail": "x"}],
        status="open",
        fingerprint="fp1",
        last_seen="2026-07-22T08:00:00+00:00",
    )
    defaults.update(kwargs)
    return AlertRecord(**defaults)


def test_markup_has_three_human_gated_ctas():
    markup = build_investigation_alert_inline_markup("alert-abcdef123456")
    rows = markup["inline_keyboard"]
    callbacks = [btn["callback_data"] for row in rows for btn in row]
    assert callbacks == [
        "jia:v:alert-abcdef123456",
        "jia:t:alert-abcdef123456",
        "jia:s:alert-abcdef123456",
    ]
    assert all(len(cb.encode("utf-8")) <= 64 for cb in callbacks)


def test_parse_alert_callback_ops():
    assert _parse_alert_callback("jia:v:alert-1") == ("v", "alert-1")
    assert _parse_alert_callback("jia:t:alert-1") == ("t", "alert-1")
    assert _parse_alert_callback("jia:s:alert-1") == ("s", "alert-1")
    assert _parse_alert_callback("jia:x:alert-1") is None
    assert _parse_alert_callback("jm:a:mission") is None


def test_format_includes_cta_hint_and_alert_id():
    msg = format_investigation_alert_message(_alert_record())
    assert "CTAs: Ver detalle · Crear tarea · Snooze 24h" in msg
    assert "Alert: alert-abcdef123456" in msg
    assert "Read-only alert — no actions executed." in msg


def test_should_not_send_when_snoozed():
    alert = _alert_record(
        status="suppressed",
        snoozed_until=(datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(),
    )
    assert alert_is_snoozed(alert) is True
    assert should_send_telegram(alert, info_enabled=False) is False


def test_snooze_persists_and_blocks_telegram_resend(alert_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ALERT_SUPPRESSION_WINDOW_HOURS", "24")
    alert_input = AlertInput(
        alert_type="dashboard_exchange_mismatch",
        source="dashboard",
        title="Mismatch",
        summary="counts differ",
        severity=AlertSeverity.CRITICAL,
        investigation_id="inv-snooze",
        normalized_finding="dashboard mismatch trigger 50001",
    )
    fp = build_fingerprint(alert_input)
    first = upsert_alert(alert_input, fingerprint=fp, suppression_window_hours=24)
    assert first.status == AlertStatus.OPEN.value

    snoozed = snooze_alert(first.alert_id, hours=24)
    assert snoozed is not None
    assert snoozed.status == AlertStatus.SUPPRESSED.value
    assert snoozed.snoozed_until
    assert alert_is_snoozed(snoozed) is True
    assert should_send_telegram(snoozed, info_enabled=False) is False

    second = upsert_alert(alert_input, fingerprint=fp, suppression_window_hours=24)
    assert second.alert_id == first.alert_id
    assert second.occurrence_count == 2
    assert second.status == AlertStatus.SUPPRESSED.value
    assert should_send_telegram(second, info_enabled=False) is False


def test_view_callback_sends_detail(alert_db, monkeypatch):
    monkeypatch.setenv("JARVIS_TELEGRAM_ENABLED", "true")
    alert_input = AlertInput(
        alert_type="t",
        source="dashboard",
        title="t",
        summary="summary line",
        severity=AlertSeverity.CRITICAL,
        investigation_id="inv-view",
        normalized_finding="view test finding",
    )
    fp = build_fingerprint(alert_input)
    record = upsert_alert(alert_input, fingerprint=fp, suppression_window_hours=24)

    sent: list[str] = []

    with (
        patch(
            "app.jarvis.investigations.alerting.telegram_inline._jarvis_alert_gate_ok",
            return_value=True,
        ),
        patch(
            "app.jarvis.investigations.alerting.telegram_inline.actor_from_telegram_user",
            return_value="@carlos",
        ),
        patch(
            "app.jarvis.investigations.persistence.get_investigation",
            return_value={
                "investigation_id": "inv-view",
                "root_cause": "Trigger order API failure blocks cache updates",
                "recommended_fix": "Allow regular open orders to update cache independently",
                "next_action": "Review evidence",
                "confidence": 0.9,
            },
        ),
    ):
        ok = handle_jarvis_investigation_alert_callback(
            chat_id="-100",
            user_id="1",
            from_user={"id": 1, "username": "carlos"},
            callback_data=f"jia:v:{record.alert_id}",
            send=sent.append,
        )
    assert ok is True
    assert len(sent) == 1
    assert "JARVIS ALERT DETAIL" in sent[0]
    assert "Trigger order API failure" in sent[0]
    assert "Read-only detail" in sent[0]


def test_create_task_fallback_queues_dry_run(alert_db, monkeypatch):
    monkeypatch.setenv("JARVIS_TELEGRAM_ENABLED", "true")
    alert_input = AlertInput(
        alert_type="t",
        source="dashboard",
        title="t",
        summary="summary",
        severity=AlertSeverity.CRITICAL,
        investigation_id="inv-task",
        normalized_finding="create task finding",
    )
    fp = build_fingerprint(alert_input)
    record = upsert_alert(alert_input, fingerprint=fp, suppression_window_hours=24)

    sent: list[str] = []
    create_mock = MagicMock()
    link_mock = MagicMock()

    with (
        patch(
            "app.jarvis.investigations.alerting.telegram_inline._jarvis_alert_gate_ok",
            return_value=True,
        ),
        patch(
            "app.jarvis.investigations.alerting.telegram_inline.actor_from_telegram_user",
            return_value="@carlos",
        ),
        patch(
            "app.jarvis.investigations.persistence.get_investigation",
            return_value={
                "investigation_id": "inv-task",
                "root_cause": "Trigger order API failure blocks cache updates",
                "recommended_fix": "Allow regular open orders independent cache update",
                "proposal_task_id": None,
                "proposal_status": None,
            },
        ),
        patch(
            "app.jarvis.proposals.config.jarvis_4b_proposals_enabled",
            return_value=False,
        ),
        patch(
            "app.jarvis.execution.persistence.create_execution_task",
            create_mock,
        ),
        patch(
            "app.jarvis.investigations.persistence.update_investigation_proposal_linkage",
            link_mock,
        ),
    ):
        ok = handle_jarvis_investigation_alert_callback(
            chat_id="-100",
            user_id="1",
            from_user={"id": 1, "username": "carlos"},
            callback_data=f"jia:t:{record.alert_id}",
            send=sent.append,
        )
    assert ok is True
    assert create_mock.called
    kwargs = create_mock.call_args.kwargs
    assert kwargs["dry_run"] is True
    assert kwargs["approval_required"] is True
    assert link_mock.called
    assert "Dry-run + approval_required" in sent[0]
    assert "ningún cambio en producción" in sent[0].lower() or "ningún cambio" in sent[0].lower()


def test_snooze_callback(alert_db, monkeypatch):
    monkeypatch.setenv("JARVIS_TELEGRAM_ENABLED", "true")
    alert_input = AlertInput(
        alert_type="t",
        source="dashboard",
        title="t",
        summary="summary",
        severity=AlertSeverity.CRITICAL,
        investigation_id="inv-s",
        normalized_finding="snooze callback finding",
    )
    fp = build_fingerprint(alert_input)
    record = upsert_alert(alert_input, fingerprint=fp, suppression_window_hours=24)
    sent: list[str] = []

    with (
        patch(
            "app.jarvis.investigations.alerting.telegram_inline._jarvis_alert_gate_ok",
            return_value=True,
        ),
        patch(
            "app.jarvis.investigations.alerting.telegram_inline.actor_from_telegram_user",
            return_value="@carlos",
        ),
    ):
        ok = handle_jarvis_investigation_alert_callback(
            chat_id="-100",
            user_id="1",
            from_user={"id": 1, "username": "carlos"},
            callback_data=f"jia:s:{record.alert_id}",
            send=sent.append,
        )
    assert ok is True
    assert "Alerta silenciada 24h" in sent[0]
    refreshed = upsert_alert(alert_input, fingerprint=fp, suppression_window_hours=24)
    assert refreshed.status == AlertStatus.SUPPRESSED.value
