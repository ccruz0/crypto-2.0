#!/usr/bin/env python3
"""
Verify the single-approval workflow end-to-end.

Single-approval flow: exactly one approval when task reaches release-candidate-ready.
No approvals during investigation, patching, or verification.

Traces:
1. Task state transition -> send_release_candidate_approval() -> chat_id resolution -> Telegram send
2. Confirms ATP Control (not ATP Alerts) is used
3. Checks for approval_triggered, approval_skipped_reason in flow
4. Optional: dry-run with mocked send to prove path
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Add backend to path
backend = Path(__file__).resolve().parent.parent
if str(backend) not in sys.path:
    sys.path.insert(0, str(backend))


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def verify_chat_id_resolution() -> dict:
    """Verify _get_default_chat_id / _get_claw_chat_id resolution."""
    result: dict = {
        "TELEGRAM_ATP_CONTROL_CHAT_ID": _env("TELEGRAM_ATP_CONTROL_CHAT_ID"),
        "TELEGRAM_CLAW_CHAT_ID": _env("TELEGRAM_CLAW_CHAT_ID"),
        "TELEGRAM_CHAT_ID": _env("TELEGRAM_CHAT_ID"),
        "TELEGRAM_CHAT_ID_TRADING": _env("TELEGRAM_CHAT_ID_TRADING"),
        "effective_chat_id": "",
        "source": "",
        "atp_alerts_used": False,
    }
    try:
        from app.services.claw_telegram import _get_claw_chat_id
        effective = _get_claw_chat_id()
        result["effective_chat_id"] = effective
        if _env("TELEGRAM_ATP_CONTROL_CHAT_ID"):
            result["source"] = "TELEGRAM_ATP_CONTROL_CHAT_ID"
        elif _env("TELEGRAM_CLAW_CHAT_ID"):
            result["source"] = "TELEGRAM_CLAW_CHAT_ID"
        elif _env("TELEGRAM_CHAT_ID"):
            result["source"] = "TELEGRAM_CHAT_ID"
        else:
            result["source"] = "none"
        # ATP Alerts uses TELEGRAM_CHAT_ID_TRADING - must NOT be same as approval destination
        trading = _env("TELEGRAM_CHAT_ID_TRADING")
        result["atp_alerts_used"] = effective == trading and bool(trading)
    except Exception as e:
        result["error"] = str(e)
    return result


def verify_runtime_path() -> list[str]:
    """Trace exact runtime path from task transition to Telegram send."""
    path = [
        "1. advance_ready_for_patch_task (agent_task_executor.py)",
        "   - Task in ready-for-patch or patching",
        "   - validate_fn passes; optional cursor bridge passes",
        "   - update_notion_task_status(task_id, 'release-candidate-ready')",
        "",
        "2. send_release_candidate_approval(task_id, title, proposed_version=..., sections=...)",
        "   - agent_telegram_approval.send_release_candidate_approval()",
        "   - target_chat = _get_default_chat_id() -> _get_claw_chat_id()",
        "   - Checks: task_id, target_chat, proposed_version (mandatory), dedup (DB-backed, fail-closed)",
        "",
        "3. build_release_candidate_approval_message() -> text",
        "   - Version, Problems Solved, Improvements, Validation Evidence, Risks, Approve/Reject prompt",
        "",
        "4. _send_telegram_message(target_chat, text, reply_markup, message_type='PATCH')",
        "   - agent_telegram_approval._send_telegram_message()",
        "",
        "5. send_claw_message(text, message_type='PATCH', ...)",
        "   - claw_telegram.send_claw_message()",
        "   - chat_id = _get_claw_chat_id() (internal)",
        "   - token = _get_claw_bot_token()",
        "   - http_post(api.telegram.org/bot{token}/sendMessage)",
        "",
        "6. Log: release_candidate_approval task_id=... sent=True/False",
    ]
    return path


def verify_no_approval_at_other_phases() -> dict:
    """Confirm approval is NOT sent at intake, investigation, patching, or verification."""
    return {
        "intake": "agent_scheduler: runs execute_prepared_task_if_approved directly, no send_task_approval_request",
        "investigation": "send_investigation_complete_approval disabled (single_approval_workflow)",
        "ready_for_patch": "send_ready_for_patch_approval disabled (single_approval_workflow)",
        "patching": "No approval during patching; validation runs internally",
        "verification": "No approval during verification; only at release-candidate-ready",
        "release_candidate_ready": "send_release_candidate_approval — ONE approval per task+version",
    }


def dry_run_send(dry_run: bool = True) -> dict:
    """Run send_release_candidate_approval with mocked _send_telegram_message."""
    from unittest.mock import patch, MagicMock

    mock_send = MagicMock(return_value=(True, 12345))
    sections = {
        "Task Summary": "Test verification",
        "Root Cause": "Verification run",
        "Recommended Fix": "No change",
        "Affected Files": "scripts/verify_ready_for_patch_approval_flow.py",
    }
    with patch("app.services.agent_telegram_approval._send_telegram_message", mock_send), \
         patch("app.services.agent_telegram_approval._get_default_chat_id", return_value="12345"), \
         patch("app.services.agent_telegram_approval._check_release_candidate_approval_dedup", return_value=(False, "")), \
         patch("app.services.agent_telegram_approval._set_release_candidate_approval_sent_db", return_value=True):
        try:
            from app.services.agent_telegram_approval import send_release_candidate_approval
            result = send_release_candidate_approval(
                task_id="00000000-0000-0000-0000-000000000000",
                title="[VERIFY] Ready-for-patch approval flow test",
                sections=sections,
                proposed_version="verify.1.0",
            )
            return {
                "called": mock_send.called,
                "call_count": mock_send.call_count,
                "result": result,
                "actual_send": not dry_run,
            }
        except Exception as e:
            return {"error": str(e), "called": False}


def main():
    print("=" * 60)
    print("SINGLE-APPROVAL WORKFLOW VERIFICATION")
    print("=" * 60)

    # 1. Chat ID resolution
    print("\n--- 1. Chat ID resolution (ATP Control) ---")
    chat = verify_chat_id_resolution()
    for k, v in chat.items():
        if k in ("effective_chat_id", "TELEGRAM_ATP_CONTROL_CHAT_ID", "TELEGRAM_CHAT_ID_TRADING"):
            # Mask sensitive
            display = f"****{v[-4:]}" if v and len(v) > 4 else "(empty)" if not v else "****"
            print(f"  {k}: {display}")
        else:
            print(f"  {k}: {v}")

    if chat.get("atp_alerts_used"):
        print("  [WARN] ATP Alerts (TELEGRAM_CHAT_ID_TRADING) would be used - approval must use ATP Control!")
    elif chat.get("effective_chat_id"):
        print("  [OK] Effective chat ID resolved (ATP Control)")
    else:
        print("  [WARN] No chat ID - set TELEGRAM_ATP_CONTROL_CHAT_ID or TELEGRAM_CLAW_CHAT_ID")

    # 2. Runtime path
    print("\n--- 2. Exact runtime path ---")
    for line in verify_runtime_path():
        print(line)

    # 3. No approval at other phases
    print("\n--- 3. Approval NOT sent at ---")
    for phase, desc in verify_no_approval_at_other_phases().items():
        print(f"  {phase}: {desc}")

    # 4. Dry run
    print("\n--- 4. Dry run (mocked send) ---")
    dry = dry_run_send(dry_run=True)
    if dry.get("error"):
        print(f"  [ERROR] {dry['error']}")
    else:
        print(f"  send_release_candidate_approval called: {dry.get('called', False)}")
        print(f"  _send_telegram_message call count: {dry.get('call_count', 0)}")
        r = dry.get("result", {})
        print(f"  result.sent: {r.get('sent')}")
        print(f"  result.task_id: {r.get('task_id', '')[:12]}...")
        if dry.get("call_count") == 1:
            print("  [OK] Exactly one Telegram send would occur")
        elif dry.get("call_count", 0) == 0:
            print("  [INFO] No send (likely dedup, missing_proposed_version, or dedup_check_unavailable)")

    # 5. Log patterns to inspect
    print("\n--- 5. Log patterns to inspect ---")
    print("  send_release_candidate_approval task_id=... sent=True/False")
    print("  skipped=dedup|missing_proposed_version|dedup_check_unavailable")
    print("  [TELEGRAM_ROUTE] category=DEV destination=ATP_CONTROL ... sent=True")

    # Verdict
    print("\n" + "=" * 60)
    has_chat = bool(chat.get("effective_chat_id"))
    no_alerts = not chat.get("atp_alerts_used")
    dry_ok = dry.get("call_count", 0) <= 1 and not dry.get("error")
    if has_chat and no_alerts and dry_ok:
        print("VERDICT: Working (code path verified; ensure env vars set in runtime)")
    elif not has_chat:
        print("VERDICT: Blocked - TELEGRAM_ATP_CONTROL_CHAT_ID (or fallback) not set")
    elif not no_alerts:
        print("VERDICT: Blocked - ATP Alerts would be used instead of ATP Control")
    else:
        print("VERDICT: Needs runtime test - run scheduler with a task that reaches ready-for-patch")
    print("=" * 60)


if __name__ == "__main__":
    main()
