# Perico (software specialist)

## Purpose

**Perico** is the software-oriented specialist profile: same `JarvisAutonomousOrchestrator` mission as `/jarvis`, but the mission prompt is wrapped so the planner/executor prioritize **engineering work** (repo, tests, logs, patches) and avoid treating the run as a marketing analytics mission.

Implementation: `app.jarvis.perico_mission` + `run_perico_from_telegram` in `app.jarvis.autonomous_orchestrator`.

## How it is invoked

- Telegram: **`/perico <task>`** (parsed in `telegram_control.classify_jarvis_command` / `dispatch_jarvis_command`).
- Requires **`JARVIS_AUTONOMOUS_ENABLED`**.
- Programmatic: `run_perico_from_telegram(text=..., actor=..., chat_id=...)`.

## Capabilities (what the platform allows)

Phase 1 adds **three registered tools** (same `TOOL_SPECS` / `invoke_registered_tool` path as the rest of Jarvis):

| Tool | Role |
|------|------|
| `perico_repo_read` | `list` / `read` / `grep` under `PERICO_REPO_ROOT` (default `/home/ubuntu/crypto-2.0`). |
| `perico_apply_patch` | Single-occurrence UTF-8 text replace; requires `PERICO_WRITE_ENABLED=1`. |
| `perico_run_pytest` | `python3 -m pytest` with cwd = repo `backend/` when present. |

`ExecutionAgent.run` invokes these when `action_type` matches **and** the mission prompt contains `[AGENT:PERICO_SOFTWARE]`; otherwise the row is `skipped`.

The planner is still steered by the wrapped prompt that tells the model to:

- Inspect the smallest relevant surface (files, tests, logs).
- Prefer **minimal** patches when justified.
- Run or request **validation** (tests / checks) when tools support it.
- **Retry** once in the mission sense where the core pipeline allows (see execution loop below).

Concrete tool names and permissions remain whatever `TOOL_SPECS` and Bedrock-produced plans allow today.

## Non-goals (by design)

- **No automatic production deploy**: stated in `build_perico_mission_prompt`; production changes still depend on real tools being absent or gated — do not rely on prompt text alone.
- **Not a separate “marketing / analytics mission”**: prompts carry `[AGENT:PERICO_SOFTWARE]`; `infer_analytics_deliverables` returns `None` for that marker so strict analytics rubrics do not apply. Google Ads deterministic merge after diagnostics is skipped in `_merge_google_ads_mutation_proposals` when the marker is present.

## Execution loop (operator + model)

1. **Understand task** from operator text (after wrap: full prompt includes “Operator software task:” section).
2. **Locate project**: hint lines `[PERICO_TARGET_PROJECT_HINT: …]` from `infer_perico_target_project` (default `crypto-2.0` when unknown).
3. **Inspect** via planned tools (files/logs/tests as available in `TOOL_SPECS`).
4. **Hypothesis** in model reasoning / plan JSON.
5. **Minimal patch** when a write tool is actually in the executed plan.
6. **Validation** when the plan includes test/diagnostic tools; executor results appear under `execution["executed"]`.
7. **Retry**: core pipeline allows **one** analytics corrective retry via `should_attempt_goal_retry` + `build_corrective_readonly_analytics_action` — **disabled** for Perico-marked prompts. Other “retries” are operator-driven (`continue_after_input`, new user text).
8. **Return**: `dialog_message` / `telegram_compact_reply_suppressed` / `waiting_for_approval` / `done` exactly like any Jarvis mission.

After execution, the orchestrator appends **`perico_deliverables`** JSON via `build_perico_deliverables_snapshot` → `NotionMissionService.append_agent_output(..., agent_name="perico_deliverables")`. The snapshot includes **`validation_command`** (last `perico_run_pytest` argv string) and **`suspected_files`** (heuristic from grep hits, read targets, list dir hints, and patched paths).

## Definition of done (practical)

“Done” in code means the pipeline reached **`MISSION_STATUS_DONE`** with reviewer output, same as other missions. For operators, Perico is successful when:

- The **stated software objective** is addressed in the final `dialog_message` / Notion readability blocks.
- **Validation** evidence exists in `execution` when the plan invoked tests/checks.
- **No silent failure**: failed tools show up in executor payloads (`error` fields) and mission may go to `failed` or `waiting_for_input` depending on branch — inspect `[AGENT_OUTPUT:execution]` in Notion.

## Safety

- **Deploy-sensitive** steps: heuristically flagged in `build_perico_deliverables_snapshot` (`deploy_sensitive`) for visibility; real enforcement is **tool policy + approvals**, not the snapshot alone.
- **Approvals**: unchanged — `waiting_for_approval` still uses the same Telegram approval UX as Jarvis.
- **Destructive tools**: only what the executor actually runs; Perico does not widen tool permissions.
