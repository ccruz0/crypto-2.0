"""Unit tests for GitHub App-backed Jarvis PR creation (no real network)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# Import change_execution first so service→pr_service wins the circular load order.
from app.jarvis.change_execution import config as _ce_config  # noqa: F401
from app.jarvis.github import pr_service as prs


def test_repo_slug_from_remote_https_and_ssh():
    assert prs._repo_slug_from_remote("https://github.com/ccruz0/crypto-2.0.git") == "ccruz0/crypto-2.0"
    assert prs._repo_slug_from_remote("git@github.com:ccruz0/crypto-2.0.git") == "ccruz0/crypto-2.0"
    assert prs._repo_slug_from_remote("") is None


def test_authed_https_remote_redacts_in_helper_shape():
    url = prs._authed_https_remote("https://github.com/ccruz0/crypto-2.0.git", "ghs_test_token")
    assert url is not None
    assert url.startswith("https://x-access-token:")
    assert "@github.com/ccruz0/crypto-2.0.git" in url
    assert "ghs_test_token" in url  # helper itself holds token; callers must not log it
    assert prs._redact_secrets(url).startswith("https://x-access-token:***@")


def test_redact_secrets_strips_pats():
    assert "[REDACTED]" in prs._redact_secrets("token ghp_ABCDEFG1234567890")
    assert "x-access-token:***@" in prs._redact_secrets("https://x-access-token:secret@github.com/a/b.git")


def test_create_pull_request_uses_github_app_api(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_PROMOTE_PR_ENABLED", "true")
    monkeypatch.delenv("JARVIS_PR_MOCK", raising=False)

    workdir = tmp_path / "sandbox"
    workdir.mkdir()

    class _Resp:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            assert "Authorization" in (headers or {})
            assert (headers or {})["Authorization"].startswith("Bearer ")
            if url.endswith("/pulls"):
                return _Resp(
                    201,
                    {
                        "html_url": "https://github.com/ccruz0/crypto-2.0/pull/407",
                        "number": 407,
                    },
                )
            if "/labels" in url:
                return _Resp(200, [])
            return _Resp(500, {"message": "unexpected"})

    with (
        patch(
            "app.services.github_app_auth.get_github_api_token",
            return_value=("ghs_fake", "github_app"),
        ),
        patch.object(prs, "_push_branch", return_value={"ok": True}) as push_mock,
        patch.object(prs.httpx, "Client", _Client),
        patch.object(prs.shutil, "which", return_value=None),
    ):
        result = prs.create_pull_request(
            task_id="task-1",
            branch_name="jarvis/lab-promote-task-1",
            title="Promote test",
            body="body",
            workdir=workdir,
            via_lab_promote=True,
            mock=False,
        )

    assert result["success"] is True
    assert result["auth_method"] == "github_app"
    assert result["transport"] == "github_api"
    assert result["pr_url"] == "https://github.com/ccruz0/crypto-2.0/pull/407"
    assert result["pr_number"] == 407
    assert result["merge"] is False
    assert result["deploy"] is False
    push_mock.assert_called_once()


def test_create_pull_request_fails_without_github_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_PROMOTE_PR_ENABLED", "true")
    monkeypatch.delenv("JARVIS_PR_MOCK", raising=False)

    with patch(
        "app.services.github_app_auth.get_github_api_token",
        return_value=("", "none"),
    ):
        result = prs.create_pull_request(
            task_id="task-2",
            branch_name="jarvis/lab-promote-task-2",
            title="Promote test",
            body="body",
            workdir=tmp_path,
            via_lab_promote=True,
            mock=False,
        )

    assert result["success"] is False
    assert "GitHub auth unavailable" in (result.get("error") or "")
    assert result.get("auth_method") == "none"


def test_create_pull_request_still_blocks_main(monkeypatch):
    monkeypatch.setenv("JARVIS_PROMOTE_PR_ENABLED", "true")
    result = prs.create_pull_request(
        task_id="task-3",
        branch_name="main",
        title="nope",
        body="body",
        workdir=MagicMock(),
        via_lab_promote=True,
        mock=False,
    )
    assert result["success"] is False
    assert "forbidden" in (result.get("error") or "").lower()
