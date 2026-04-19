"""Jarvis Telegram + Notion mission UX (inline buttons, readability layers)."""

from __future__ import annotations

import uuid

from app.jarvis.notion_mission_readability import (
    format_executive_summary_block,
    format_timeline_line,
    human_mission_status,
)
from app.jarvis.telegram_mission_markup import build_jarvis_mission_inline_markup


def test_callback_payload_fits_telegram_64_byte_limit():
    mid = str(uuid.uuid4())
    for mode in ("input", "approval", "details_only"):
        kb = build_jarvis_mission_inline_markup(mid, mode)  # type: ignore[arg-type]
        for row in kb.get("inline_keyboard") or []:
            for btn in row:
                cb = str(btn.get("callback_data") or "")
                if cb:
                    assert len(cb) <= 64, f"callback_data too long: {len(cb)} {cb!r}"


def test_executive_summary_and_timeline_tags():
    s = format_executive_summary_block(
        objective="Analyze Ads",
        status="Falta tu respuesta",
        what_jarvis_did="Ran planner",
        key_result="Needs scope",
        next_step="Reply",
    )
    assert "[EXEC_SUMMARY]" in s
    assert "Objetivo:" in s and "Analyze Ads" in s
    assert "Qué hizo Jarvis:" in s
    tl = format_timeline_line("Planner started.")
    assert tl.startswith("[TIMELINE]")


def test_human_mission_status_labels():
    assert "respuesta" in human_mission_status("waiting_for_input").lower()
    assert human_mission_status("done") == "Completada"
