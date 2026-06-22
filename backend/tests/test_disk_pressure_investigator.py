"""Tests for the read-only HostDiskFillingUp disk-pressure investigator.

No real Bedrock and no real SSM: the provider and runner are both injected fakes.
"""

from __future__ import annotations

import pytest

from app.jarvis.investigations.investigators import disk_pressure as dp
from app.jarvis.investigations.investigators.disk_evidence import DiskRecommendation
from app.jarvis.llm.provider import LLMResponse
from app.services.atp_ssm_runner import is_command_allowed

_SECRET_LINE = "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIxxxxxxxxxxxxxxxxxxxxxxxxEXAMPLE"


class _FakeProvider:
    def __init__(self) -> None:
        self.last_prompt: str | None = None
        self.last_system: str | None = None

    def complete(self, prompt, *, system=None, max_tokens=1024, temperature=0.0):
        self.last_prompt = prompt
        self.last_system = system
        return LLMResponse(text="Build cache is large; consider docker image prune.", model_id="m-test")


def _fake_runner_factory():
    calls: list[str] = []

    def runner(cmd: str, **_kwargs) -> dict:
        calls.append(cmd)
        out = {
            "df -h /": "Filesystem Size Used Avail Use% Mounted on\n/dev/root 49G 47G 2G 96% /",
            "free -h": "              total        used        free\nMem:           1.9Gi       1.6Gi       0.1Gi",
            # plant a secret to prove scrubbing happens before the model call
            "docker compose --profile aws ps": f"NAME STATUS\nbackend Up\n{_SECRET_LINE}",
        }.get(cmd, "")
        return {"ok": True, "stdout": out, "stderr": "", "status": "Success", "error": None}

    return runner, calls


def test_fail_closed_when_investigator_flag_off(monkeypatch):
    monkeypatch.delenv("JARVIS_DISK_INVESTIGATOR_ENABLED", raising=False)
    monkeypatch.setenv("JARVIS_BEDROCK_ENABLED", "true")
    with pytest.raises(dp.DiskInvestigatorDisabled):
        dp.investigate(provider=_FakeProvider(), runner=_fake_runner_factory()[0])


def test_fail_closed_when_bedrock_flag_off(monkeypatch):
    monkeypatch.setenv("JARVIS_DISK_INVESTIGATOR_ENABLED", "true")
    monkeypatch.delenv("JARVIS_BEDROCK_ENABLED", raising=False)
    with pytest.raises(dp.DiskInvestigatorDisabled):
        dp.investigate(provider=_FakeProvider(), runner=_fake_runner_factory()[0])


def test_gather_only_uses_allowlisted_commands():
    runner, calls = _fake_runner_factory()
    dp.gather_disk_evidence(runner=runner)
    assert calls == ["df -h /", "free -h", "docker compose --profile aws ps"]
    for cmd in calls:
        allowed, _ = is_command_allowed(cmd)
        assert allowed, f"{cmd} must be allowlisted"
    # the deliberately excluded commands are never issued
    assert "docker system df" not in calls
    assert not any(c.startswith("docker inspect") for c in calls)


def test_investigate_returns_text_only_and_scrubs_prompt(monkeypatch):
    monkeypatch.setenv("JARVIS_DISK_INVESTIGATOR_ENABLED", "true")
    monkeypatch.setenv("JARVIS_BEDROCK_ENABLED", "true")
    provider = _FakeProvider()
    runner, _ = _fake_runner_factory()

    rec = dp.investigate(provider=provider, runner=runner)

    assert isinstance(rec, DiskRecommendation)
    assert rec.alert == "HostDiskFillingUp"
    assert rec.suggested_action == "Build cache is large; consider docker image prune."
    assert rec.model_id == "m-test"
    assert len(rec.evidence.commands) == 3

    # the secret value must have been scrubbed out of the prompt sent to the model
    assert provider.last_prompt is not None
    assert "wJalrXUtnFEMI" not in provider.last_prompt
    assert "AWS_SECRET_ACCESS_KEY=" in provider.last_prompt  # key name remains, value redacted

    # recommendation is a plain pydantic model: text fields only, nothing callable
    for value in rec.model_dump().values():
        assert not callable(value)
