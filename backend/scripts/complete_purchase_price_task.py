#!/usr/bin/env python3
"""
Complete the purchase_price task (10d75276-fcff-48bc-b5c9-473dec72bebd) end-to-end:
1. Move task to Patching
2. Generate cursor handoff if missing
3. Run Cursor Bridge
4. Verify patch proof
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TASK_ID = "10d75276-fcff-48bc-b5c9-473dec72bebd"


def main():
    results = {
        "task_id": TASK_ID,
        "current_status": None,
        "handoff_path": None,
        "handoff_existed": False,
        "cursor_bridge_ran": False,
        "cursor_bridge_ok": False,
        "patch_proof_found": False,
        "deploy_allowed": False,
    }

    # 1. Move task to Patching
    try:
        from app.services.notion_task_reader import get_notion_task_by_id
        from app.services.notion_tasks import update_notion_task_status

        task = get_notion_task_by_id(TASK_ID)
        if not task:
            print("ERROR: Task not found in Notion")
            results["error"] = "task_not_found"
            print(json.dumps(results, indent=2))
            return 1

        current = (task.get("status") or "").strip().lower()
        results["current_status"] = current

        if current not in ("patching", "ready-for-patch"):
            ok = update_notion_task_status(
                TASK_ID,
                "patching",
                append_comment="[Script] Moved to Patching for Cursor Bridge execution.",
            )
            if ok:
                results["current_status"] = "patching"
                print("Moved task to Patching")
            else:
                print("WARN: Could not update Notion status")
    except Exception as e:
        print(f"Notion update failed: {e}")
        results["error"] = str(e)

    # 2. Check/generate handoff (writable dir matches backend get_writable_cursor_handoffs_dir)
    root = Path(__file__).resolve().parents[2]
    try:
        from app.services._paths import get_writable_cursor_handoffs_dir

        handoff_path = get_writable_cursor_handoffs_dir() / f"cursor-handoff-{TASK_ID}.md"
    except Exception:
        handoff_path = root / "docs" / "agents" / "cursor-handoffs" / f"cursor-handoff-{TASK_ID}.md"
    results["handoff_path"] = str(handoff_path)

    if handoff_path.exists():
        results["handoff_existed"] = True
        print(f"Handoff exists: {handoff_path}")
    else:
        try:
            from app.services.cursor_handoff import generate_cursor_handoff

            sections_path = root / "docs" / "agents" / "bug-investigations" / f"notion-bug-{TASK_ID}.sections.json"
            sections = {}
            if sections_path.exists():
                data = json.loads(sections_path.read_text(encoding="utf-8"))
                sections = data.get("sections") or {}
                # Affected Files: cursor_handoff expects newline-separated; sidecar may have comma-separated
                af = sections.get("Affected Files") or ""
                if af and "," in af and "\n" not in af:
                    sections["Affected Files"] = "\n".join(f.strip() for f in af.split(",") if f.strip())

            prepared = {
                "task": {"id": TASK_ID, "task": "RESET: purchase_price becomes null/missing"},
                "_openclaw_sections": sections,
                "repo_area": {},
            }
            out = generate_cursor_handoff(prepared, sections=sections)
            if out.get("success") and out.get("path"):
                results["handoff_existed"] = False
                results["handoff_path"] = out["path"]
                print(f"Generated handoff: {out['path']}")
            else:
                print("ERROR: Failed to generate handoff")
                results["error"] = "handoff_generation_failed"
        except Exception as e:
            print(f"Handoff generation failed: {e}")
            results["error"] = str(e)
            print(json.dumps(results, indent=2))
            return 1

    # 3. Run Cursor Bridge
    bridge_enabled = (os.environ.get("CURSOR_BRIDGE_ENABLED") or "").strip().lower() in ("1", "true", "yes")
    if not bridge_enabled:
        print("CURSOR_BRIDGE_ENABLED not set — skipping bridge run")
        results["cursor_bridge_ran"] = False
        results["cursor_bridge_ok"] = False
    else:
        try:
            from app.services.cursor_execution_bridge import run_bridge_phase2, is_bridge_enabled

            if not is_bridge_enabled():
                print("Bridge not enabled (check CURSOR_BRIDGE_ENABLED, Cursor CLI)")
                results["cursor_bridge_ran"] = False
            else:
                print("Running Cursor Bridge...")
                bridge_result = run_bridge_phase2(
                    task_id=TASK_ID,
                    ingest=True,
                    create_pr=False,
                    current_status="patching",
                    execution_context="telegram",
                )
                results["cursor_bridge_ran"] = True
                results["cursor_bridge_ok"] = bridge_result.get("ok", False)
                results["cursor_bridge_tests_ok"] = bridge_result.get("tests_ok", False)
                if bridge_result.get("ok"):
                    print("Cursor Bridge: OK")
                else:
                    print(f"Cursor Bridge failed: {bridge_result.get('error', 'unknown')}")
        except Exception as e:
            print(f"Cursor Bridge error: {e}")
            results["cursor_bridge_ran"] = True
            results["cursor_bridge_ok"] = False
            results["cursor_bridge_error"] = str(e)

    # 4. Verify patch proof
    try:
        from app.services.patch_proof import has_patch_proof, cursor_bridge_required_for_task
        from app.services.notion_task_reader import get_notion_task_by_id

        task = get_notion_task_by_id(TASK_ID)
        proof_ok, proof_reason = has_patch_proof(TASK_ID, task)
        results["patch_proof_found"] = proof_ok
        results["patch_proof_reason"] = proof_reason

        required, req_reason = cursor_bridge_required_for_task(task or {}, TASK_ID)
        results["deploy_allowed"] = not required
        results["deploy_block_reason"] = req_reason if required else None
    except Exception as e:
        results["patch_proof_error"] = str(e)

    print(json.dumps(results, indent=2))
    return 0 if results.get("deploy_allowed") else 1


if __name__ == "__main__":
    sys.exit(main())
