"""Tests for Jarvis Telegram formatting (ATP system review)."""

from __future__ import annotations

from app.jarvis import telegram_control as tc


def test_format_run_atp_system_review_telegram_sorted_and_capped():
    payload = {
        "jarvis_run_id": "r1",
        "plan": {"action": "run_atp_system_review", "args": {}, "reasoning": "t"},
        "result": {
            "status": "degraded",
            "environment": "lab",
            "scope": "quick",
            "summary": "System is running but has high-priority configuration gaps. (3 action(s)).",
            "actions": [
                {"message": "Second", "priority": "HIGH"},
                {"message": "First critical", "priority": "CRITICAL"},
                {"message": "Third medium", "priority": "MEDIUM"},
                {"message": "Dup of Second", "priority": "LOW"},
            ],
        },
    }
    out = tc.format_compact_jarvis_reply("jarvis", payload)
    assert "🧠 ATP System Review" in out
    assert "Summary:" in out
    assert "Actions:" in out
    assert "[CRITICAL]" in out and "First critical" in out
    hi = out.index("[HIGH]")
    cr = out.index("[CRITICAL]")
    me = out.index("[MEDIUM]")
    assert cr < hi < me
    assert "Warnings:" not in out
    assert "Improvements:" not in out
    assert "Suggested Actions:" not in out
    assert "{" not in out
    assert "run r1" in out


def test_format_atp_defensive_dedupe_same_message():
    payload = {
        "jarvis_run_id": "",
        "plan": {"action": "run_atp_system_review", "args": {}, "reasoning": "t"},
        "result": {
            "status": "ok",
            "environment": "lab",
            "scope": "full",
            "summary": "No issues detected for this review scope.",
            "actions": [
                {"message": "Same text", "priority": "HIGH", "source": "config"},
                {"message": "same text", "priority": "MEDIUM", "source": "config"},
            ],
        },
    }
    out = tc.format_compact_jarvis_reply("jarvis", payload)
    assert out.count("Same text") + out.count("same text") == 1


def test_format_atp_max_seven_actions():
    acts = [{"message": f"A{i}", "priority": "LOW"} for i in range(10)]
    payload = {
        "jarvis_run_id": "",
        "plan": {"action": "run_atp_system_review", "args": {}, "reasoning": "t"},
        "result": {
            "status": "degraded",
            "environment": "lab",
            "scope": "full",
            "summary": "x",
            "actions": acts,
        },
    }
    out = tc.format_compact_jarvis_reply("jarvis", payload)
    assert out.count("• [") == 7


def test_format_atp_executor_error():
    payload = {
        "jarvis_run_id": "",
        "plan": {"action": "run_atp_system_review", "args": {}, "reasoning": "t"},
        "result": {"error": "tool_failed", "detail": "boom"},
    }
    out = tc.format_compact_jarvis_reply("jarvis", payload)
    assert "Error:" in out
    assert "tool_failed" in out


def test_format_dialog_message_short_circuits():
    payload = {"dialog_message": "Hello", "jarvis_run_id": "", "plan": {}, "result": None}
    assert tc.format_compact_jarvis_reply("jarvis", payload) == "Hello"


def test_process_jarvis_telegram_message_empty_without_intake():
    from app.jarvis.dialog_state import reset_store_for_tests

    reset_store_for_tests()
    assert tc.process_jarvis_telegram_message("hello", "9", "9") == {}


def test_secure_secret_intake_telegram_path_no_echo(tmp_path):
    from app.jarvis.dialog_state import get_state, reset_store_for_tests
    from app.jarvis.telegram_secret_intake import begin_marketing_setting_intake, handle_secret_intake_turn

    reset_store_for_tests()
    rt = str(tmp_path / "runtime.env")

    intro = begin_marketing_setting_intake(
        "c1",
        "u1",
        setting_key="google_ads_developer_token",
        resume_action="run_marketing_review",
        resume_args={},
        runtime_env_path_override=rt,
    )
    assert "Google Ads Developer Token" in intro
    assert "dashboard" in intro.lower() and "telegram" in intro.lower()

    t1 = handle_secret_intake_turn("telegram", chat_id="c1", user_id="u1", runtime_env_path_override=rt)
    assert "next message" in t1["dialog_message"].lower()

    secret = "ULTRA_SECRET_VALUE_XYZ_42"
    t2 = handle_secret_intake_turn(secret, chat_id="c1", user_id="u1", runtime_env_path_override=rt)
    assert "saved" in t2["dialog_message"].lower()
    assert secret not in str(t2)
    assert t2.get("resume_plan", {}).get("action") == "run_marketing_review"

    formatted = tc.format_compact_jarvis_reply(
        "jarvis",
        {"dialog_message": t2["dialog_message"], "resume_plan": t2.get("resume_plan"), "plan": {}, "result": None},
    )
    assert secret not in formatted
    assert "Warnings:" not in formatted and "Improvements:" not in formatted

    st = get_state("c1", "u1")
    assert st is None or (not st.pending_secret_key and not st.pending_secret_phase)

    content = (tmp_path / "runtime.env").read_text(encoding="utf-8")
    assert "JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN=" in content
    assert secret in content


def test_secret_intake_cancel_during_choose(tmp_path):
    from app.jarvis.dialog_state import get_state, reset_store_for_tests
    from app.jarvis.telegram_secret_intake import begin_marketing_setting_intake, handle_secret_intake_turn

    reset_store_for_tests()
    rt = str(tmp_path / "runtime.env")
    begin_marketing_setting_intake(
        "c2",
        "u2",
        setting_key="google_ads_developer_token",
        runtime_env_path_override=rt,
    )
    out = handle_secret_intake_turn("cancel", chat_id="c2", user_id="u2", runtime_env_path_override=rt)
    assert "cancelled" in out["dialog_message"].lower()
    st = get_state("c2", "u2")
    assert st is None or not (st.pending_secret_key and st.pending_secret_phase)


def test_non_secret_setting_direct_value(tmp_path):
    from app.jarvis.dialog_state import reset_store_for_tests
    from app.jarvis.telegram_secret_intake import begin_marketing_setting_intake, handle_secret_intake_turn

    reset_store_for_tests()
    rt = str(tmp_path / "runtime.env")
    intro = begin_marketing_setting_intake(
        "c3",
        "u3",
        setting_key="ga4_property_id",
        runtime_env_path_override=rt,
    )
    assert "Google Analytics Property ID" in intro
    assert "dashboard" not in intro.lower()

    out = handle_secret_intake_turn("123456789", chat_id="c3", user_id="u3", runtime_env_path_override=rt)
    assert "saved" in out["dialog_message"].lower()
    assert (tmp_path / "runtime.env").read_text(encoding="utf-8").count("JARVIS_GA4_PROPERTY_ID=") == 1


def test_invalid_secret_value_generic_error(tmp_path):
    from app.jarvis.dialog_state import reset_store_for_tests
    from app.jarvis.telegram_secret_intake import begin_marketing_setting_intake, handle_secret_intake_turn

    reset_store_for_tests()
    rt = str(tmp_path / "runtime.env")
    begin_marketing_setting_intake(
        "c4",
        "u4",
        setting_key="ga4_property_id",
        runtime_env_path_override=rt,
    )
    bad = "not-a-number"
    out = handle_secret_intake_turn(bad, chat_id="c4", user_id="u4", runtime_env_path_override=rt)
    assert "invalid" in out["dialog_message"].lower() or "dashboard" in out["dialog_message"].lower()
    assert bad not in out["dialog_message"]


def test_dashboard_choice_clears_intake(tmp_path):
    from app.jarvis.dialog_state import get_state, reset_store_for_tests
    from app.jarvis.telegram_secret_intake import begin_marketing_setting_intake, handle_secret_intake_turn

    reset_store_for_tests()
    rt = str(tmp_path / "runtime.env")
    begin_marketing_setting_intake(
        "c5",
        "u5",
        setting_key="google_ads_developer_token",
        runtime_env_path_override=rt,
    )
    out = handle_secret_intake_turn("dashboard", chat_id="c5", user_id="u5", runtime_env_path_override=rt)
    assert "dashboard" in out["dialog_message"].lower()
    st = get_state("c5", "u5")
    assert st is None or not (st.pending_secret_key and st.pending_secret_phase)


def test_duplicate_begin_overwrites_single_pending(tmp_path):
    from app.jarvis.dialog_state import get_state, reset_store_for_tests
    from app.jarvis.telegram_secret_intake import begin_marketing_setting_intake

    reset_store_for_tests()
    rt = str(tmp_path / "runtime.env")
    begin_marketing_setting_intake("c6", "u6", setting_key="google_ads_developer_token", runtime_env_path_override=rt)
    begin_marketing_setting_intake("c6", "u6", setting_key="google_ads_developer_token", runtime_env_path_override=rt)
    st = get_state("c6", "u6")
    assert st is not None
    assert st.pending_secret_key == "google_ads_developer_token"
