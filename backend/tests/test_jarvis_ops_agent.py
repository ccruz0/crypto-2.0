from __future__ import annotations

import json
import sys
import types
from typing import Any

from app.jarvis.autonomous_agents import ExecutionAgent, _classify_google_ads_error, run_google_ads_readonly_diagnostic
from app.jarvis.autonomous_orchestrator import JarvisAutonomousOrchestrator
from app.jarvis.autonomous_agents import StrategyAgent
from app.jarvis.ops_agent import OpsAgent
from app.jarvis.telegram_service import TelegramMissionService


def _strategy_with(action: dict[str, Any]) -> dict[str, Any]:
    return {"actions": [action], "source": "test"}


def test_diagnose_google_ads_setup_missing_env_vars(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.ops_tools.inspect_container_env",
        lambda container_name, env_prefixes=None: {
            "success": True,
            "env": {"JARVIS_GOOGLE_ADS_CREDENTIALS_JSON": "/run/secrets/google-ads.json"},
            "count": 1,
            "container_name": container_name,
        },
    )
    monkeypatch.setattr(
        "app.jarvis.ops_tools.inspect_container_mounts",
        lambda container_name: {
            "success": True,
            "mounts": [{"source": "/host/secrets", "destination": "/run/secrets"}],
            "count": 1,
            "container_name": container_name,
        },
    )
    monkeypatch.setattr(
        "app.jarvis.ops_tools.check_path_in_container",
        lambda container_name, path: {"success": True, "exists": True, "path": path},
    )

    out = OpsAgent()._run_auto_action(
        "diagnose_google_ads_setup",
        {"container_name": "backend-aws"},
        {"findings": ["Google Ads not configured"]},
    )

    messages = [str(d.get("message") or "") for d in out["diagnostics"]]
    assert any("missing env vars" in m for m in messages)
    assert any(x.get("action_type") == "update_runtime_env" for x in out["waiting_for_approval"])


def test_diagnose_google_ads_setup_missing_file_in_container(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.ops_tools.inspect_container_env",
        lambda *args, **kwargs: {
            "success": True,
            "env": {
                "JARVIS_GOOGLE_ADS_CREDENTIALS_JSON": "/run/secrets/google-ads.json",
                "JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN": "x",
                "JARVIS_GOOGLE_ADS_CUSTOMER_ID": "y",
            },
        },
    )
    monkeypatch.setattr(
        "app.jarvis.ops_tools.inspect_container_mounts",
        lambda *args, **kwargs: {
            "success": True,
            "mounts": [{"source": "/host/secrets", "destination": "/run/secrets"}],
            "count": 1,
        },
    )
    monkeypatch.setattr(
        "app.jarvis.ops_tools.check_path_in_container",
        lambda *args, **kwargs: {"success": False, "exists": False},
    )

    out = OpsAgent()._run_auto_action(
        "diagnose_google_ads_setup",
        {"container_name": "backend-aws"},
        {"findings": []},
    )
    messages = [str(d.get("message") or "") for d in out["diagnostics"]]
    assert any("not present inside the running container" in m for m in messages)
    assert any(x.get("action_type") == "restart_backend" for x in out["waiting_for_approval"])


def test_diagnose_google_ads_setup_mount_source_present_but_credentials_absent(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.ops_tools.inspect_container_env",
        lambda *args, **kwargs: {
            "success": True,
            "env": {
                "JARVIS_GOOGLE_ADS_CREDENTIALS_JSON": "/run/secrets/google-ads.json",
                "JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN": "x",
                "JARVIS_GOOGLE_ADS_CUSTOMER_ID": "y",
            },
        },
    )
    monkeypatch.setattr(
        "app.jarvis.ops_tools.inspect_container_mounts",
        lambda *args, **kwargs: {
            "success": True,
            "mounts": [{"source": "/mounted/secrets", "destination": "/run/secrets"}],
            "count": 1,
        },
    )
    monkeypatch.setattr(
        "app.jarvis.ops_tools.check_path_in_container",
        lambda *args, **kwargs: {"success": False, "exists": False},
    )
    monkeypatch.setattr(
        "app.jarvis.ops_tools.check_path_on_host",
        lambda path: {"success": True, "exists": False, "path": path},
    )

    out = OpsAgent()._run_auto_action(
        "diagnose_google_ads_setup",
        {
            "container_name": "backend-aws",
            "host_credentials_path": "/mounted/secrets/google-ads.json",
        },
        {"findings": []},
    )
    messages = [str(d.get("message") or "") for d in out["diagnostics"]]
    assert any("does not exist on host path" in m for m in messages)


def test_diagnose_google_ads_setup_all_required_config_present(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.ops_tools.inspect_container_env",
        lambda *args, **kwargs: {
            "success": True,
            "env": {
                "JARVIS_GOOGLE_ADS_CREDENTIALS_JSON": "/run/secrets/google-ads.json",
                "JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN": "x",
                "JARVIS_GOOGLE_ADS_CUSTOMER_ID": "y",
            },
        },
    )
    monkeypatch.setattr(
        "app.jarvis.ops_tools.inspect_container_mounts",
        lambda *args, **kwargs: {
            "success": True,
            "mounts": [{"source": "/host/secrets", "destination": "/run/secrets"}],
            "count": 1,
        },
    )
    monkeypatch.setattr(
        "app.jarvis.ops_tools.check_path_in_container",
        lambda *args, **kwargs: {"success": True, "exists": True},
    )

    out = OpsAgent()._run_auto_action(
        "diagnose_google_ads_setup",
        {"container_name": "backend-aws"},
        {"findings": []},
    )
    messages = [str(d.get("message") or "") for d in out["diagnostics"]]
    assert any("appears complete" in m for m in messages)
    assert out["waiting_for_approval"] == []


def test_ops_agent_auto_exec_and_requires_approval_actions(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.ops_tools.inspect_container_env",
        lambda *args, **kwargs: {"success": True, "env": {"JARVIS_X": "1"}, "count": 1},
    )

    strategy = {
        "actions": [
            {
                "title": "Inspect env",
                "action_type": "inspect_container_env",
                "params": {"container_name": "backend-aws"},
                "execution_mode": "auto_execute",
                "priority_score": 70,
            },
            {
                "title": "Fix credential path",
                "action_type": "fix_credentials_path",
                "params": {},
                "execution_mode": "requires_approval",
                "priority_score": 90,
            },
            {
                "title": "Update runtime env",
                "action_type": "update_runtime_env",
                "params": {},
                "execution_mode": "requires_approval",
                "priority_score": 91,
            },
            {
                "title": "Restart backend",
                "action_type": "restart_backend",
                "params": {},
                "execution_mode": "requires_approval",
                "priority_score": 92,
            },
        ]
    }
    out = OpsAgent().run(prompt="x", plan={}, research={}, strategy=strategy)
    assert any(x.get("action_type") == "inspect_container_env" for x in out["auto_executed"])
    approval_types = {x.get("action_type") for x in out["waiting_for_approval"]}
    assert {"fix_credentials_path", "update_runtime_env", "restart_backend"}.issubset(approval_types)


def test_strategy_agent_adds_ops_diagnosis_actions_when_not_configured(monkeypatch):
    monkeypatch.setattr("app.jarvis.autonomous_agents.ask_bedrock", lambda prompt: '{"actions":[]}')
    monkeypatch.setattr("app.jarvis.autonomous_agents.extract_planner_json_object", lambda raw: {"actions": []})
    out = StrategyAgent().run(
        prompt="Google Ads not configured",
        plan={},
        research={"findings": ["Google Ads not configured"]},
        outcome_memory=[],
    )
    action_types = {str(a.get("action_type") or "") for a in out.get("actions", []) if isinstance(a, dict)}
    assert "diagnose_google_ads_setup" in action_types


class _FakeNotion:
    def __init__(self) -> None:
        self.state = "received"
        self.id = "mission-ops"
        self.events: list[tuple[str, str, str]] = []

    def configured(self) -> bool:
        return True

    def create_mission(self, *, prompt: str, actor: str) -> dict:
        _ = prompt, actor
        return {"mission_id": self.id, "status": self.state}

    def get_mission(self, mission_id: str) -> dict | None:
        if mission_id != self.id:
            return None
        return {"mission_id": mission_id, "status": self.state, "task": "Mission"}

    def transition_state(self, mission_id: str, *, to_state: str, note: str = "") -> bool:
        _ = note
        self.events.append((mission_id, "state", to_state))
        self.state = to_state
        return True

    def append_agent_output(self, mission_id: str, *, agent_name: str, content: str) -> None:
        self.events.append((mission_id, agent_name, content))

    def append_event(self, mission_id: str, *, event: str, detail: str = "") -> None:
        self.events.append((mission_id, event, detail))

    def get_recent_outcomes(self, mission_id: str, *, limit: int = 25) -> list[dict]:
        _ = mission_id, limit
        return []

    def append_action_baseline(self, mission_id: str, *, action: dict) -> None:
        self.events.append((mission_id, "baseline", str(action.get("title") or "")))

    def append_outcome_evaluation(self, mission_id: str, *, evaluations: list[dict], summary: dict) -> None:
        self.events.append((mission_id, "outcome_eval", f"{len(evaluations)}:{summary.get('total', 0)}"))

    def append_readability_executive_summary(self, mission_id: str, **kwargs) -> None:
        self.events.append((mission_id, "readability_summary", str(kwargs.get("status") or "")))

    def append_readability_timeline(self, mission_id: str, sentence: str) -> None:
        self.events.append((mission_id, "readability_timeline", sentence[:200]))

    def append_technical_detail_marker(self, mission_id: str, title: str = "") -> None:
        self.events.append((mission_id, "technical_marker", title))


class _FakeTelegram:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_approval_request(self, chat_id: str, mission_id: str, summary: str) -> bool:
        self.messages.append(f"approval:{chat_id}:{mission_id}:{summary}")
        return True

    def send_input_request(self, chat_id: str, mission_id: str, question: str) -> bool:
        self.messages.append(f"input:{chat_id}:{mission_id}:{question}")
        return True

    def send_ops_report(self, chat_id: str, ops_output: dict) -> bool:
        self.messages.append(f"ops:{chat_id}:{bool(ops_output)}")
        return True


class _PlannerSimple:
    def run(self, prompt: str) -> dict:
        _ = prompt
        return {
            "objective": "simple",
            "steps": ["s1"],
            "requires_research": False,
            "requires_input": False,
        }


class _StrategySimple:
    def run(self, *, prompt: str, plan: dict, research: dict | None, outcome_memory=None) -> dict:
        _ = prompt, plan, research, outcome_memory
        return {
            "actions": [
                {
                    "title": "Safe analysis action",
                    "action_type": "analysis",
                    "execution_mode": "auto_execute",
                    "priority_score": 60,
                    "params": {},
                }
            ]
        }


class _ExecutionSimple:
    def run(self, *, strategy: dict | None, mission_prompt: str = ""):
        _ = strategy, mission_prompt
        return {
            "executed": [{"title": "Safe analysis action", "action_type": "analysis", "execution_mode": "auto_execute"}],
            "waiting_for_approval": [],
            "waiting_for_input": [],
            "needs_approval": False,
            "approval_summary": "",
        }


class _ReviewPass:
    def run(self, *, plan: dict, execution: dict) -> dict:
        _ = plan, execution
        return {"passed": True, "summary": "ok"}


class _OpsStub:
    def run(self, prompt: str, plan: dict, research: dict | None, strategy: dict) -> dict:
        _ = prompt, plan, research, strategy
        return {
            "diagnostics": [{"severity": "error", "message": "Google Ads is marked not configured."}],
            "proposed_fixes": [],
            "auto_executed": [{"action_type": "inspect_container_env"}],
            "waiting_for_approval": [],
            "waiting_for_input": [],
            "summary": "ops checked",
            "success": False,
        }


def test_orchestrator_includes_ops_output_and_logs_to_notion():
    fake_notion = _FakeNotion()
    fake_telegram = _FakeTelegram()
    orch = JarvisAutonomousOrchestrator(
        notion=fake_notion,
        planner=_PlannerSimple(),
        strategist=_StrategySimple(),
        ops=_OpsStub(),
        executor=_ExecutionSimple(),
        reviewer=_ReviewPass(),
        telegram=fake_telegram,
    )
    out = orch.run_new_mission(prompt="check", actor="@ops", chat_id="123")
    assert out["status"] == "done"
    assert "ops" in out["result"]
    assert any(ev[1] == "ops" for ev in fake_notion.events), "ops output must be logged to Notion"


def test_telegram_ops_report_is_readable_and_redacts_values():
    sent: list[str] = []
    svc = TelegramMissionService()
    svc.send_message = lambda chat_id, text: sent.append(f"{chat_id}:{text}") or True  # type: ignore[method-assign]

    ok = svc.send_ops_report(
        "chat-1",
        {
            "diagnostics": [
                {"message": "Google Ads is marked not configured because credentials are missing in container."},
                {"message": "JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN=super-secret-token"},
            ],
            "waiting_for_approval": [{"action_type": "fix_credentials_path"}],
        },
    )
    assert ok is True
    body = sent[0]
    assert "Google Ads is marked not configured" in body
    assert "super-secret-token" not in body
    assert "[REDACTED]" in body
    assert "¿Apruebas mover credenciales de Google Ads al directorio de secretos y reiniciar el backend?" in body


def test_execution_agent_google_ads_diagnostic_returns_real_payload(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.autonomous_agents.run_google_ads_readonly_diagnostic",
        lambda params: {
            "auth_ok": True,
            "campaign_fetch_ok": True,
            "campaign_count": 3,
            "campaigns": ["A", "B"],
            "error_type": None,
            "error_message": None,
        },
    )
    out = ExecutionAgent().run(
        strategy={
            "actions": [
                {
                    "title": "Google Ads diagnostic",
                    "action_type": "diagnose_google_ads_setup",
                    "params": {},
                    "execution_mode": "auto_execute",
                    "priority_score": 88,
                }
            ]
        }
    )
    executed = out["executed"][0]
    assert executed["status"] == "executed"
    assert executed["result"]["auth_ok"] is True
    assert executed["result"]["campaign_fetch_ok"] is True
    assert executed["result"]["campaign_count"] == 3


def test_google_ads_diagnostic_missing_credentials_returns_structured_failure(monkeypatch):
    monkeypatch.delenv("JARVIS_GOOGLE_ADS_CREDENTIALS_JSON", raising=False)
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_CUSTOMER_ID", "123-456-7890")
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN", "dev-token")
    out = run_google_ads_readonly_diagnostic({})
    assert out["auth_ok"] is False
    assert out["campaign_fetch_ok"] is False
    assert out["error_type"] == "credentials"
    assert "credentials json path is missing" in str(out["error_message"]).lower()


def test_google_ads_error_classification_oauth():
    err = _classify_google_ads_error("invalid_grant oauth token rejected by provider")
    assert err == "oauth"


def test_google_ads_error_classification_user_permission_denied():
    err = _classify_google_ads_error("authorization_error: USER_PERMISSION_DENIED User doesn't have permission")
    assert err == "permissions"


def test_done_dialog_includes_google_ads_execution_result():
    orch = JarvisAutonomousOrchestrator()
    text = orch._build_done_dialog_message(  # noqa: SLF001
        mission_id="m1",
        prompt="Run Google Ads diagnostic",
        plan={"source": "bedrock"},
        research={"source": "bedrock"},
        strategy={
            "source": "bedrock",
            "actions": [{"action_type": "diagnose_google_ads_setup", "title": "Google Ads diagnostic"}],
        },
        ops_output={"diagnostics": []},
        execution={
            "executed": [
                {
                    "action_type": "diagnose_google_ads_setup",
                    "title": "Google Ads diagnostic",
                    "result": {
                        "auth_ok": True,
                        "campaign_fetch_ok": True,
                        "campaign_count": 5,
                        "campaigns": ["Campaign A"],
                        "error_type": None,
                        "error_message": None,
                    },
                }
            ]
        },
        review={"summary": "ok"},
    )
    assert "Autenticación con Google Ads: correcta." in text
    assert "Campañas obtenidas: 5." in text
    assert "Muestra de campañas: Campaign A" in text
    assert "Ref. interna: m1" in text


def test_google_ads_diagnostic_missing_refresh_token_returns_oauth(monkeypatch, tmp_path):
    creds = tmp_path / "google_ads_oauth.json"
    creds.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "oauth-client-id",
                    "client_secret": "oauth-client-secret",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_CREDENTIALS_JSON", str(creds))
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_CUSTOMER_ID", "123-456-7890")
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN", "dev-token")
    monkeypatch.delenv("JARVIS_GOOGLE_ADS_REFRESH_TOKEN", raising=False)

    out = run_google_ads_readonly_diagnostic({})
    assert out["auth_ok"] is False
    assert out["campaign_fetch_ok"] is False
    assert out["error_type"] == "oauth"
    assert "refresh token is missing" in str(out["error_message"]).lower()


def test_google_ads_diagnostic_invalid_oauth_json_shape(monkeypatch, tmp_path):
    creds = tmp_path / "google_ads_bad.json"
    creds.write_text(json.dumps({"installed": {"client_id": "only-id"}}), encoding="utf-8")
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_CREDENTIALS_JSON", str(creds))
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_CUSTOMER_ID", "123-456-7890")
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN", "dev-token")
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_REFRESH_TOKEN", "refresh-token")

    out = run_google_ads_readonly_diagnostic({})
    assert out["auth_ok"] is False
    assert out["campaign_fetch_ok"] is False
    assert out["error_type"] == "credentials"
    assert "client_id and client_secret" in str(out["error_message"])


def test_google_ads_diagnostic_uses_oauth_fields_not_service_account(monkeypatch, tmp_path):
    creds = tmp_path / "google_ads_oauth.json"
    creds.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "oauth-client-id",
                    "client_secret": "oauth-client-secret",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_CREDENTIALS_JSON", str(creds))
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_CUSTOMER_ID", "123-456-7890")
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN", "dev-token")
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_LOGIN_CUSTOMER_ID", "999-999-9999")

    class _FakeGoogleAdsClient:
        last_config: dict[str, Any] | None = None

        @classmethod
        def load_from_dict(cls, config: dict[str, Any]):
            cls.last_config = dict(config)
            return _FakeClient()

    class _FakeCampaign:
        def __init__(self, name: str) -> None:
            self.name = name

    class _FakeRow:
        def __init__(self, name: str = "") -> None:
            self.campaign = _FakeCampaign(name)

    class _FakeService:
        def search(self, request: Any):
            q = str(getattr(request, "query", "")).lower()
            if "from customer" in q:
                return iter([_FakeRow("")])
            if "from campaign" in q:
                return iter([_FakeRow("Campaign A"), _FakeRow("Campaign B")])
            return iter([])

    class _FakeRequest:
        customer_id = ""
        query = ""

    class _FakeClient:
        def get_service(self, name: str):
            assert name == "GoogleAdsService"
            return _FakeService()

        def get_type(self, name: str):
            assert name == "SearchGoogleAdsRequest"
            return _FakeRequest()

    fake_client_module = types.SimpleNamespace(GoogleAdsClient=_FakeGoogleAdsClient)
    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.ads", types.ModuleType("google.ads"))
    monkeypatch.setitem(sys.modules, "google.ads.googleads", types.ModuleType("google.ads.googleads"))
    monkeypatch.setitem(sys.modules, "google.ads.googleads.client", fake_client_module)

    out = run_google_ads_readonly_diagnostic({})
    assert out["auth_ok"] is True
    assert out["campaign_fetch_ok"] is True
    assert out["campaign_count"] == 2
    assert out["campaigns"] == ["Campaign A", "Campaign B"]
    assert _FakeGoogleAdsClient.last_config is not None
    assert _FakeGoogleAdsClient.last_config.get("client_id") == "oauth-client-id"
    assert _FakeGoogleAdsClient.last_config.get("client_secret") == "oauth-client-secret"
    assert _FakeGoogleAdsClient.last_config.get("refresh_token") == "refresh-token"
    assert _FakeGoogleAdsClient.last_config.get("login_customer_id") == "9999999999"
    assert "json_key_file_path" not in _FakeGoogleAdsClient.last_config


def test_google_ads_diagnostic_does_not_set_page_size_on_search_request(monkeypatch, tmp_path):
    """Regression: newer Google Ads API rejects assigning page_size on SearchGoogleAdsRequest."""
    creds = tmp_path / "google_ads_oauth.json"
    creds.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "oauth-client-id",
                    "client_secret": "oauth-client-secret",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_CREDENTIALS_JSON", str(creds))
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_CUSTOMER_ID", "1234567890")
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN", "dev-token")
    monkeypatch.setenv("JARVIS_GOOGLE_ADS_REFRESH_TOKEN", "refresh-token")
    monkeypatch.delenv("JARVIS_GOOGLE_ADS_LOGIN_CUSTOMER_ID", raising=False)

    class _SearchRequestNoPageSize:
        __slots__ = ("customer_id", "query")

        def __init__(self) -> None:
            self.customer_id = ""
            self.query = ""

    class _FakeGoogleAdsClient:
        last_config: dict[str, Any] | None = None

        @classmethod
        def load_from_dict(cls, config: dict[str, Any]):
            cls.last_config = dict(config)
            return _FakeClient()

    class _FakeCampaign:
        def __init__(self, name: str) -> None:
            self.name = name

    class _FakeRow:
        def __init__(self, name: str = "") -> None:
            self.campaign = _FakeCampaign(name)

    class _FakeService:
        def search(self, request: Any):
            q = str(getattr(request, "query", "")).lower()
            if "from customer" in q:
                return iter([_FakeRow("")])
            if "from campaign" in q:
                return iter([_FakeRow("OnlyCampaign")])
            return iter([])

    class _FakeClient:
        def get_service(self, name: str):
            assert name == "GoogleAdsService"
            return _FakeService()

        def get_type(self, name: str):
            assert name == "SearchGoogleAdsRequest"
            return _SearchRequestNoPageSize()

    fake_client_module = types.SimpleNamespace(GoogleAdsClient=_FakeGoogleAdsClient)
    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.ads", types.ModuleType("google.ads"))
    monkeypatch.setitem(sys.modules, "google.ads.googleads", types.ModuleType("google.ads.googleads"))
    monkeypatch.setitem(sys.modules, "google.ads.googleads.client", fake_client_module)

    out = run_google_ads_readonly_diagnostic({})
    assert out["auth_ok"] is True
    assert out["campaign_fetch_ok"] is True
    assert out["campaign_count"] == 1
    assert out["campaigns"] == ["OnlyCampaign"]
