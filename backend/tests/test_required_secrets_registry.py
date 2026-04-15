"""Tests for required_secrets_registry (no real secrets)."""

import pytest

from app.services.required_secrets_registry import evaluate_requirements, is_allowed_intake_key


def test_trading_only_mode_skips_automation_requirements(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATP_TRADING_ONLY", "1")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    for k in (
        "NOTION_API_KEY",
        "NOTION_TASK_DB",
        "OPENCLAW_API_TOKEN",
        "OPENCLAW_API_URL",
        "GITHUB_APP_ID",
    ):
        monkeypatch.delenv(k, raising=False)

    out = evaluate_requirements()
    assert out["overall"] == "ok"
    assert out["missing"] == []
    ar = out["automation_readiness"]
    assert ar["applicable"] is True
    assert ar["overall"] == "action_required"
    ar_vars = {m["env_var"] for m in ar["missing"]}
    assert "GITHUB_APP_ID" in ar_vars
    assert "NOTION_API_KEY" in ar_vars


def test_automation_readiness_not_duplicated_when_automation_active(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATP_TRADING_ONLY", "0")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    monkeypatch.setenv("NOTION_API_KEY", "k")
    monkeypatch.setenv("NOTION_TASK_DB", "db")
    monkeypatch.setenv("OPENCLAW_API_TOKEN", "t")
    monkeypatch.setenv("OPENCLAW_API_URL", "http://x:1")
    monkeypatch.setenv("GITHUB_APP_ID", "1")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "2")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_B64", "e30=")

    out = evaluate_requirements()
    assert out["automation_readiness"]["applicable"] is False


def test_automation_mode_reports_missing_notion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATP_TRADING_ONLY", "0")
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    monkeypatch.delenv("NOTION_TASK_DB", raising=False)
    monkeypatch.setenv("OPENCLAW_API_TOKEN", "x")
    monkeypatch.setenv("OPENCLAW_API_URL", "http://example:8080")

    out = evaluate_requirements()
    assert out["overall"] == "action_required"
    vars_missing = {m["env_var"] for m in out["missing"]}
    assert "NOTION_API_KEY" in vars_missing
    assert "NOTION_TASK_DB" in vars_missing


def test_github_app_required_on_aws_when_not_trading_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATP_TRADING_ONLY", "0")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    monkeypatch.setenv("NOTION_API_KEY", "k")
    monkeypatch.setenv("NOTION_TASK_DB", "db")
    monkeypatch.setenv("OPENCLAW_API_TOKEN", "t")
    monkeypatch.setenv("OPENCLAW_API_URL", "http://x:1")
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("ALLOW_LEGACY_GITHUB_PAT", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    out = evaluate_requirements()
    vars_missing = {m["env_var"] for m in out["missing"]}
    assert "GITHUB_APP_ID" in vars_missing


def test_legacy_pat_skips_github_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATP_TRADING_ONLY", "0")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    monkeypatch.setenv("NOTION_API_KEY", "k")
    monkeypatch.setenv("NOTION_TASK_DB", "db")
    monkeypatch.setenv("OPENCLAW_API_TOKEN", "t")
    monkeypatch.setenv("OPENCLAW_API_URL", "http://x:1")
    monkeypatch.setenv("ALLOW_LEGACY_GITHUB_PAT", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_xxxxx")
    for g in ("GITHUB_APP_ID", "GITHUB_APP_INSTALLATION_ID", "GITHUB_APP_PRIVATE_KEY_B64"):
        monkeypatch.delenv(g, raising=False)

    out = evaluate_requirements()
    gh_missing = [m for m in out["missing"] if m["env_var"].startswith("GITHUB_APP_")]
    assert gh_missing == []


def test_github_app_client_id_status_missing_when_core_set_on_aws(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATP_TRADING_ONLY", "1")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    monkeypatch.setenv("GITHUB_APP_ID", "1")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "2")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_B64", "e30=")
    monkeypatch.delenv("GITHUB_APP_CLIENT_ID", raising=False)
    monkeypatch.delenv("ALLOW_LEGACY_GITHUB_PAT", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    out = evaluate_requirements()
    assert out["context"]["github_app_client_id_status"] == "missing"


def test_github_app_client_id_status_present_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATP_TRADING_ONLY", "1")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    monkeypatch.setenv("GITHUB_APP_ID", "1")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "2")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_B64", "e30=")
    monkeypatch.setenv("GITHUB_APP_CLIENT_ID", "Iv1.abc")

    out = evaluate_requirements()
    assert out["context"]["github_app_client_id_status"] == "present"


def test_github_app_client_id_status_not_applicable_legacy_pat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "aws")
    monkeypatch.setenv("GITHUB_APP_ID", "1")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "2")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_B64", "e30=")
    monkeypatch.setenv("ALLOW_LEGACY_GITHUB_PAT", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_xx")

    out = evaluate_requirements()
    assert out["context"]["github_app_client_id_status"] == "not_applicable"


def test_intake_allows_github_app_client_id() -> None:
    assert is_allowed_intake_key("GITHUB_APP_CLIENT_ID") is True


def test_intake_allows_exchange_and_rejects_unknown() -> None:
    assert is_allowed_intake_key("EXCHANGE_CUSTOM_API_KEY") is True
    assert is_allowed_intake_key("ADMIN_ACTIONS_KEY") is False


def test_secrets_catalog_masks_and_presence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXCHANGE_CUSTOM_API_KEY", "mysecretkeyvalue")
    monkeypatch.delenv("EXCHANGE_CUSTOM_API_SECRET", raising=False)
    out = evaluate_requirements()
    cat = {r["env_var"]: r for r in out["secrets_catalog"]}
    assert cat["EXCHANGE_CUSTOM_API_KEY"]["present"] is True
    assert cat["EXCHANGE_CUSTOM_API_KEY"]["masked"].endswith("lue")
    assert cat["EXCHANGE_CUSTOM_API_SECRET"]["present"] is False
    assert cat["EXCHANGE_CUSTOM_API_SECRET"]["masked"] == "(empty)"
