"""Tests for deploy_trigger GitHub auth integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_trigger_deploy_workflow_uses_github_app_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")

    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_resp.text = ""

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.post.return_value = mock_resp

    with (
        patch(
            "app.services.github_app_auth.get_github_api_token",
            return_value=("ghs_test_token", "github_app"),
        ),
        patch("app.services.deploy_trigger.httpx.Client", return_value=mock_client),
    ):
        from app.services.deploy_trigger import trigger_deploy_workflow

        result = trigger_deploy_workflow(task_id="task-1", triggered_by="tester")

    assert result["ok"] is True
    assert result["status_code"] == 204
    headers = mock_client.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer ghs_test_token"


def test_trigger_deploy_workflow_fails_without_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    with patch(
        "app.services.github_app_auth.get_github_api_token",
        return_value=("", "none"),
    ):
        from app.services.deploy_trigger import trigger_deploy_workflow

        result = trigger_deploy_workflow(task_id="task-2")

    assert result["ok"] is False
    assert "auth unavailable" in result["error"].lower()
