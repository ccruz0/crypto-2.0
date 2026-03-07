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
        "PREFIX_APPROVE": "agent_approve:", "PREFIX_DENY": "agent_deny:",
        "PREFIX_SUMMARY": "agent_summary:", "PREFIX_EXECUTE": "agent_execute:",
    })
    _stub("app.services.agent_activity_log", {"log_agent_event": _mock(), "get_recent_agent_events": _mock(return_value=[])})


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
