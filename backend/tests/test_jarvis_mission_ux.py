"""Jarvis Telegram + Notion mission UX (inline buttons, readability layers)."""

from __future__ import annotations

import uuid

from app.jarvis.notion_mission_readability import (
    format_executive_summary_block,
    format_timeline_line,
    human_mission_status,
    notion_executive_display_fields,
)
from app.jarvis.perico_mission import PERICO_AGENT_MARKER, build_perico_mission_prompt
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
        agent="Perico",
        project="crypto-2.0",
        task_type="validación",
    )
    assert "[EXEC_SUMMARY]" in s
    assert "Objetivo:" in s and "Analyze Ads" in s
    assert "Agente: Perico" in s
    assert "Proyecto: crypto-2.0" in s
    assert "Tipo de tarea: validación" in s
    assert "Qué hizo Jarvis:" in s
    tl = format_timeline_line("Planner started.")
    assert tl.startswith("[TIMELINE]")


def test_human_mission_status_labels():
    assert "respuesta" in human_mission_status("waiting_for_input").lower()
    assert human_mission_status("done") == "Completada"


def test_notion_executive_display_strips_perico_wrapped_prompt():
    wrapped = build_perico_mission_prompt(user_text="Validar tests en crypto-2.0")
    nf = notion_executive_display_fields(wrapped, specialist_agent="perico")
    assert "[AGENT:" not in nf["objective"]
    assert "Registered Perico tools" not in nf["objective"]
    assert "Validar tests" in nf["objective"] or "crypto-2.0" in nf["objective"]
    assert nf["agent"] == "Perico"
    assert nf["project"]
    assert nf["task_type"] == "validación"

    plain = format_executive_summary_block(
        objective=nf["objective"],
        status="Recibida",
        agent=nf["agent"],
        project=nf["project"],
        task_type=nf["task_type"],
    )
    assert "[AGENT:PERICO" not in plain


def test_notion_executive_fields_strip_marker_but_keep_operator_line_objective():
    full = build_perico_mission_prompt(
        user_text="Hay un problema con los tests. Aplica parche y pytest.",
    )
    stripped = full.replace(PERICO_AGENT_MARKER, "").lstrip()
    nf = notion_executive_display_fields(stripped, specialist_agent=None)
    assert nf["agent"] == "Perico"
    assert "Registered Perico tools" not in nf["objective"]
    assert "Hay un problema" in nf["objective"] or "tests" in nf["objective"].lower()
