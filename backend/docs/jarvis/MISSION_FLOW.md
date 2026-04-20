# Mission flow (runtime)

All paths below are in `app.jarvis.autonomous_orchestrator` unless noted.

## Entry points

| Source | Function | Notes |
|--------|----------|--------|
| Telegram `/jarvis` (autonomous on) | `run_autonomous_jarvis_from_telegram` | `run_new_mission(prompt=text, …)` |
| Telegram `/perico` | `run_perico_from_telegram` | `run_new_mission(..., specialist_agent="perico")` — prompt wrapped with `build_perico_mission_prompt` |
| Telegram `/mission …` | `handle_mission_command` | status / approve / reject / input → `continue_after_*` |

Telegram parsing: `app.jarvis.telegram_control`.

## `_run_pipeline` (single mission cycle)

States use `MISSION_STATUS_*` in `app.jarvis.autonomous_schemas`.

1. **Planning**  
   - `transition_state(..., PLANNING)`  
   - If Perico: extra readability timeline line (software loop reminder).  
   - `PlannerAgent.run(prompt)` → logged as `[AGENT_OUTPUT:planner]`.

2. **Optional clarification**  
   - If `plan["requires_input"]` and no `external_input`: `WAITING_FOR_INPUT`, `send_input_request`, return (may set `telegram_compact_reply_suppressed`).

3. **Research (optional)**  
   - If `plan["requires_research"]`: `ResearchAgent.run`.

4. **Strategy**  
   - `StrategyAgent.run` → `[AGENT_OUTPUT:strategy]`.

5. **Ops**  
   - `OpsAgent.run` → `[AGENT_OUTPUT:ops]`, `send_ops_report` to Telegram.

6. **Execution**  
   - `transition_state(..., EXECUTING)`  
   - `ExecutionAgent.run` in a loop with `evaluate_goal_satisfaction` after each pass.  
   - For `auto_execute` rows whose `action_type` is `perico_repo_read` / `perico_apply_patch` / `perico_run_pytest`, the agent calls `invoke_registered_tool` (Perico-marked missions only).  
   - If rubric says not satisfied and `should_attempt_goal_retry`: replace actions with `build_corrective_readonly_analytics_action` once (**skipped for Perico-marked prompts**).

7. **Perico snapshot + validation gate (if Perico)**  
   - After the execution loop: optional **one** automatic `perico_run_pytest` retry via `perico_try_auto_pytest_retry` when a patch succeeded and the first pytest failed.  
   - `build_perico_deliverables_snapshot` → `[AGENT_OUTPUT:perico_deliverables]`.  
   - If `perico_should_block_for_operator_input` fires (e.g. patch without pytest, or pytest still red after retry), the mission returns `WAITING_FOR_INPUT` instead of continuing to merge/review.

8. **Goal shortfall**  
   - If not satisfied: `WAITING_FOR_INPUT`, `format_goal_shortfall_user_message`, `send_input_request`, return.

9. **Post-goal Google Ads merge (Jarvis analytics path only)**  
   - If satisfied: `_merge_google_ads_mutation_proposals` may append deterministic pause/budget/resume proposals (**skipped when `is_perico_marked_prompt(prompt)`**).

10. **Outcome evaluator**  
    - `OutcomeEvaluatorAgent.evaluate` on executed rows.

11. **Branches**  
    - `waiting_for_input` inside execution → input Telegram flow.  
    - Combined `waiting_for_approval` (ops + execution) → `send_approval_request`, `WAITING_FOR_APPROVAL` (duplicate compact reply suppressed in `telegram_control` when send succeeds).  
    - Else reviewer (`ReviewAgent.run`) and `DONE` / `FAILED` depending on plan/review paths already in the orchestrator.

## Where Perico fits

- Same `_run_pipeline` as Jarvis.  
- Differences: **wrapped prompt**, **timeline note**, **analytics rubric / merge / analytics retry disabled** via marker checks, **Notion `perico_deliverables` blob** after execution.

## Related modules (quick index)

- Orchestrator: `autonomous_orchestrator.py`  
- Perico helpers: `perico_mission.py`  
- Goal rubric: `mission_goal_quality.py`, `analytics_mission_deliverables.py`  
- Telegram: `telegram_control.py`, `telegram_service.py`, `telegram_mission_inline.py`  
- Notion: `notion_mission_service.py`
