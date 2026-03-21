"""Tests for agent approval callback routing in Telegram commands.

Validates that agent_approve: / agent_deny: / agent_summary: callbacks
are routed to _handle_agent_approval_callback instead of 'Unknown command'.
"""
import importlib
import sys
import types
import os
import time
import pytest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Stub heavy third-party and app modules BEFORE importing telegram_commands.
# ---------------------------------------------------------------------------

_STUBS_INSTALLED: dict = {}


def _stub(name, attrs=None):
    mod = types.ModuleType(name)
    if attrs:
        for k, v in attrs.items():
            setattr(mod, k, v)
    _STUBS_INSTALLED[name] = mod
    sys.modules[name] = mod
    return mod


def _install_stubs():
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "fake-token")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")
    os.environ.setdefault("TELEGRAM_AUTH_USER_ID", "12345")

    _mock = MagicMock
    _fake_resp = MagicMock(status_code=200, content=b'{"ok":true}')
    _fake_resp.json.return_value = {"ok": True, "result": []}
    _fake_resp.raise_for_status.return_value = None

    _stub("sqlalchemy", {"Column": _mock(), "String": _mock(), "Integer": _mock(),
        "Boolean": _mock(), "Float": _mock(), "DateTime": _mock(), "Text": _mock(),
        "create_engine": _mock(), "text": _mock(), "inspect": _mock(),
        "and_": _mock(), "not_": _mock(), "or_": _mock()})
    _stub("sqlalchemy.orm", {"Session": _mock, "sessionmaker": _mock(), "relationship": _mock(),
        "declarative_base": _mock(return_value=_mock())})
    _stub("sqlalchemy.sql", {"func": _mock()})
    _stub("sqlalchemy.ext", {})
    _stub("sqlalchemy.ext.declarative", {"declarative_base": _mock(return_value=_mock())})
    _stub("requests", {"post": _mock(), "get": _mock()})
    exc = _stub("requests.exceptions", {"HTTPError": type("H", (Exception,), {}), "RequestException": type("R", (Exception,), {})})
    sys.modules["requests"].exceptions = exc
    _stub("pytz", {"timezone": _mock(), "utc": _mock()})

    _stub("app.core.config", {"Settings": _mock(), "settings": _mock()})
    _stub("app.core.runtime", {"is_aws_runtime": _mock(return_value=False), "get_runtime_origin": _mock(return_value="local")})
    _stub("app.core.environment", {"getRuntimeEnv": _mock(return_value="local")})
    _stub("app.database", {"SessionLocal": _mock(), "engine": _mock()})
    _stub("app.utils.http_client", {"http_get": MagicMock(return_value=_fake_resp), "http_post": MagicMock(return_value=_fake_resp), "requests_exceptions": exc})
    _stub("app.models.watchlist", {"WatchlistItem": _mock()})
    _stub("app.models.watchlist_item", {"WatchlistItem": _mock()})
    _stub("app.models.trading_settings", {"TradingSettings": _mock()})
    _stub("app.models.exchange_order", {"ExchangeOrder": _mock()})
    _stub("app.models.exchange_balance", {"ExchangeBalance": _mock()})
    _stub("app.models.trade_signal", {"TradeSignal": _mock()})
    _stub("app.models.telegram_message", {"TelegramMessage": _mock()})
    _stub("app.models.telegram_state", {"TelegramState": _mock()})
    _stub("app.models.agent_approval_state", {"AgentApprovalState": _mock()})
    _stub("app.services.telegram_notifier", {"telegram_notifier": _mock()})
    _stub("app.services.exchange_sync", {"sync_exchange_data": _mock()})
    _stub("app.services.signal_monitor", {})
    _stub("app.services.daily_summary", {})
    _stub("app.services.agent_telegram_approval", {
        "get_approval_summary_text": _mock(return_value="summary"),
        "execute_prepared_task_from_telegram_decision": _mock(return_value={"executed": True, "execution_result": {"final_status": "ok"}}),
        "record_approval": _mock(return_value=True), "record_denial": _mock(return_value=True),
        "get_pending_approvals": _mock(return_value=[]),
        "clear_task_approval_record": _mock(),
        "get_openclaw_report_for_task": _mock(return_value=None),
        "PREFIX_APPROVE": "agent_approve:", "PREFIX_DENY": "agent_deny:",
        "PREFIX_SUMMARY": "agent_summary:", "PREFIX_EXECUTE": "agent_execute:",
        "PREFIX_APPROVE_PATCH": "patch_approve:", "PREFIX_APPROVE_DEPLOY": "deploy_approve:",
        "PREFIX_REJECT": "task_reject:", "PREFIX_VIEW_REPORT": "view_report:",
        "PREFIX_SMOKE_CHECK": "smoke_check:", "PREFIX_REINVESTIGATE": "reinvestigate:",
        "PREFIX_RUN_CURSOR_BRIDGE": "run_cursor_bridge:",
    })
    _stub("app.services.agent_activity_log", {"log_agent_event": _mock(), "get_recent_agent_events": _mock(return_value=[])})
    _stub("app.services.task_compiler", {
        "create_task_from_telegram_intent": _mock(return_value={
            "ok": True, "title": "Test", "type": "Investigation", "status": "Planned",
            "priority": 50, "priority_label": "medium", "reused": False,
        }),
        "ERROR_NOTION_NOT_CONFIGURED": "Notion is not configured",
    })


_install_stubs()

import app.services.telegram_commands as tc  # noqa: E402

_COUNTER = 0


def _make_callback_update(callback_data, chat_id="12345", user_id="12345"):
    global _COUNTER
    _COUNTER += 1
    return {
        "update_id": 10000 + _COUNTER,
        "callback_query": {
            "id": f"cb_{_COUNTER}",
            "data": callback_data,
            "from": {"id": int(user_id), "username": "testuser"},
            "message": {"message_id": 42 + _COUNTER, "chat": {"id": int(chat_id)}},
        },
    }


def _make_text_update(text: str, chat_id: str = "12345", user_id: str = "12345"):
    """Build a text message update (no callback_query)."""
    global _COUNTER
    _COUNTER += 1
    return {
        "update_id": 10000 + _COUNTER,
        "message": {
            "message_id": 50 + _COUNTER,
            "text": text,
            "chat": {"id": int(chat_id), "type": "private"},
            "from": {"id": int(user_id), "username": "testuser", "first_name": "Test"},
        },
    }


@pytest.fixture(autouse=True)
def _clear_dedup_state():
    """Clear deduplication caches between tests."""
    tc.PROCESSED_CALLBACK_IDS.clear()
    tc.PROCESSED_CALLBACK_DATA.clear()
    tc.PROCESSED_TEXT_COMMANDS.clear()
    if hasattr(tc.handle_telegram_update, "processed_update_ids"):
        tc.handle_telegram_update.processed_update_ids.clear()
    yield


class TestApprovalCallbackRouting:

    def test_approve_routes_to_handler(self):
        with patch.object(tc, "_handle_agent_approval_callback") as mock_h, \
             patch.object(tc, "http_post", return_value=MagicMock(status_code=200, json=lambda: {"ok": True})):
            tc.handle_telegram_update(_make_callback_update("agent_approve:abc-123"), db=None)
            mock_h.assert_called_once()

    def test_deny_routes_to_handler(self):
        with patch.object(tc, "_handle_agent_approval_callback") as mock_h, \
             patch.object(tc, "http_post", return_value=MagicMock(status_code=200, json=lambda: {"ok": True})):
            tc.handle_telegram_update(_make_callback_update("agent_deny:def-456"), db=None)
            mock_h.assert_called_once()

    def test_summary_routes_to_handler(self):
        with patch.object(tc, "_handle_agent_approval_callback") as mock_h, \
             patch.object(tc, "http_post", return_value=MagicMock(status_code=200, json=lambda: {"ok": True})):
            tc.handle_telegram_update(_make_callback_update("agent_summary:ghi-789"), db=None)
            mock_h.assert_called_once()

    def test_exception_sends_error_not_unknown(self):
        with patch.object(tc, "_handle_agent_approval_callback", side_effect=RuntimeError("boom")), \
             patch.object(tc, "send_command_response") as mock_send, \
             patch.object(tc, "http_post", return_value=MagicMock(status_code=200, json=lambda: {"ok": True})):
            tc.handle_telegram_update(_make_callback_update("agent_approve:exc-test"), db=None)
            all_msg = " ".join(str(c) for c in mock_send.call_args_list)
            assert "Unknown command" not in all_msg

    def test_unknown_callback_still_triggers_unknown(self):
        with patch.object(tc, "send_command_response") as mock_send, \
             patch.object(tc, "http_post", return_value=MagicMock(status_code=200, json=lambda: {"ok": True})):
            tc.handle_telegram_update(_make_callback_update("totally_unknown:xyz"), db=None)
            all_msg = " ".join(str(c) for c in mock_send.call_args_list)
            assert "Unknown command" in all_msg


class TestReinvestigateCallbackRouting:
    """Re-investigate callback routes to extended approval handler."""

    def test_reinvestigate_routes_to_extended_handler(self):
        with patch.object(tc, "_handle_extended_approval_callback") as mock_ext, \
             patch.object(tc, "http_post", return_value=MagicMock(status_code=200, json=lambda: {"ok": True})):
            tc.handle_telegram_update(
                _make_callback_update("reinvestigate:31cb1837-03fe-8045-b8a8-e27cca1198e0"),
                db=None,
            )
            mock_ext.assert_called_once()
            call_kw = mock_ext.call_args
            assert call_kw[0][4] == "reinvestigate"  # action
            assert "31cb1837-03fe-8045-b8a8-e27cca1198e0" in call_kw[0][3]  # callback_data

    def test_reinvestigate_callback_data_format(self):
        """reinvestigate:<task_id> format is used (callback_data max 64 bytes)."""
        task_id = "31cb1837-03fe-8045-b8a8-e27cca1198e0"
        callback_data = f"reinvestigate:{task_id}"
        assert len(callback_data) <= 64, "Telegram callback_data limit is 64 bytes"
        assert callback_data.startswith("reinvestigate:")

    def test_reinvestigate_notion_success_updates_status_and_confirms(self):
        """Re-investigate with successful Notion write shows success message."""
        task_id = "31cb1837-03fe-8045-b8a8-e27cca1198e0"
        task = {"id": task_id, "status": "blocked", "task": "Test task"}
        with patch("app.services.notion_task_reader.get_notion_task_by_id", return_value=task), \
             patch("app.services.notion_tasks.update_notion_task_status", return_value=True), \
             patch.object(tc, "_edit_approval_card") as mock_edit, \
             patch.object(tc, "send_command_response") as mock_send, \
             patch.object(tc, "http_post", return_value=MagicMock(status_code=200, json=lambda: {"ok": True})):
            tc.handle_telegram_update(
                _make_callback_update(f"reinvestigate:{task_id}"),
                db=None,
            )
            mock_edit.assert_called()
            edit_msg = mock_edit.call_args[0][2]  # result_text (chat_id, message_id, result_text, task_id)
            assert "ready-for-investigation" in edit_msg
            assert "Notion status update failed" not in edit_msg
            send_msgs = " ".join(str(c[0][1]) for c in mock_send.call_args_list if len(c[0]) > 1)
            assert "Re-investigation started" in send_msgs or "ready-for-investigation" in edit_msg

    def test_reinvestigate_notion_failure_shows_error_and_records_for_spam_suppression(self):
        """Re-investigate with failed Notion write shows error, records for stuck-alert suppression."""
        task_id = "31cb1837-03fe-8045-b8a8-e27cca1198e0"
        task = {"id": task_id, "status": "blocked", "task": "Test task"}
        with patch("app.services.notion_task_reader.get_notion_task_by_id", return_value=task), \
             patch("app.services.notion_tasks.update_notion_task_status", return_value=False), \
             patch("app.services.task_health_monitor.record_reinvestigate_failed") as mock_record, \
             patch.object(tc, "_edit_approval_card") as mock_edit, \
             patch.object(tc, "http_post", return_value=MagicMock(status_code=200, json=lambda: {"ok": True})):
            tc.handle_telegram_update(
                _make_callback_update(f"reinvestigate:{task_id}"),
                db=None,
            )
            mock_edit.assert_called()
            edit_msg = mock_edit.call_args[0][2]  # result_text
            assert "Notion status update failed" in edit_msg
            assert "blocked" in edit_msg or "unknown" in edit_msg
            mock_record.assert_called_once_with(task_id)


class TestTaskTextRouting:
    """ /task text command routes to task handler, never to unknown-command."""

    def test_task_foo_routes_to_task_handler_not_unknown(self):
        """ /task something must NEVER trigger 'Unknown command'."""
        with patch.object(tc, "send_command_response") as mock_send:
            tc.handle_telegram_update(
                _make_text_update("/task Critical: Telegram task command is failing in production"),
                db=None,
            )
            calls = mock_send.call_args_list
            assert len(calls) >= 1, "At least one response"
            all_msg = " ".join(str(c[0][1]) for c in calls if len(c[0]) > 1)
            assert "Unknown command" not in all_msg, "/task must never reach unknown-command branch"
            assert "Task created" in all_msg or "Create task" in all_msg or "Matched existing" in all_msg

    def test_task_at_botname_routes_to_task_handler(self):
        with patch.object(tc, "send_command_response") as mock_send:
            tc.handle_telegram_update(
                _make_text_update("/task@ATP_control_bot Fix order mismatch"),
                db=None,
            )
            calls = mock_send.call_args_list
            assert len(calls) >= 1
            all_msg = " ".join(str(c[0][1]) for c in calls if len(c[0]) > 1)
            assert "Unknown command" not in all_msg

    def test_unknown_command_still_returns_unknown(self):
        with patch.object(tc, "send_command_response") as mock_send:
            tc.handle_telegram_update(
                _make_text_update("/nonexistent_command"),
                db=None,
            )
            all_msg = " ".join(str(c) for c in mock_send.call_args_list)
            assert "Unknown command" in all_msg

    def test_help_still_works(self):
        with patch.object(tc, "send_command_response") as mock_send, \
             patch.object(tc, "send_help_message") as mock_help:
            mock_help.return_value = True
            tc.handle_telegram_update(_make_text_update("/help"), db=None)
            mock_help.assert_called_once()
