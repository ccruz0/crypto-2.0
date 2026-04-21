"""mission_operator_guidance: stable operator strings for guided Telegram + Notion."""

from __future__ import annotations

from app.jarvis.mission_operator_guidance import (
    notion_options_from_guided_profile,
    resolve_guided_mission_input_text,
)


def test_resolve_guided_runtime_retry_uses_repo_hint():
    t = resolve_guided_mission_input_text(
        "retr",
        ctx={"profile": "perico_repo_path", "repo_root_hint": "/app", "fallback_root": "/app"},
    )
    assert t and "/app" in t
    assert "[PERICO_ENV PERICO_REPO_ROOT=" in t


def test_resolve_guided_unknown_code():
    assert resolve_guided_mission_input_text("nope", ctx={"profile": "generic_wait"}) is None


def test_notion_options_align_with_buttons():
    labels = notion_options_from_guided_profile("generic_wait", ctx={})
    assert len(labels) == 4
    assert any("test" in x.lower() for x in labels)
