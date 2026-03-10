# Human approval gate (agents)

This document describes the **lightweight approval gate** that determines whether a prepared task may be executed automatically or must wait for explicit human approval.

Implementation: `backend/app/services/agent_approval.py` and the helpers `prepare_task_with_approval_check` / `execute_prepared_task_if_approved` in `agent_task_executor.py`.

---

## Why the approval gate exists

The agent workflow can prepare and execute tasks via injected callbacks. To keep risk bounded:

- **Low-risk** tasks (documentation notes, monitoring triage notes under `/docs`) may run without human approval.
- **Higher-risk** tasks (anything touching trading, orders, exchange, runtime, or deploy) must not run until a human has explicitly approved execution.

The gate does not store who approved what; it only answers “is approval required?” and “was approval granted for this run?” (passed in by the caller).

---

## Auto-eligible (no approval required)

Execution may proceed without approval when **all** of the following hold:

1. A **known safe callback** is selected (documentation or monitoring triage).
2. The task title and details do **not** contain high-risk keywords (see below).
3. The inferred repo area does **not** indicate trading, exchange, order sync, market execution, telegram command handling, infra runtime, or deploy logic.

In that case the gate returns `required=False`, `risk_level="low"`, and the executor may run the callbacks immediately.

---

## Approval required

Execution is **blocked** (must pass `approved=True` to run) when **any** of the following hold:

- **No known safe callback** — No apply callback was selected, or the selected callback is not in the approved low-risk set (documentation, monitoring triage).
- **High-risk keywords in task** — The task title or details contain any of:  
  `trade`, `trading`, `order`, `exchange`, `execution`, `deploy`, `restart`, `nginx`, `docker-compose`, `crypto.com`, `signal`, `strategy`, `telegram_commands`.
- **High-risk inferred area** — The inferred repo area (name or matched rules) indicates:  
  trading, exchange, order(s), market execution, telegram, notifications, infrastructure, deploy, strategy, signal.
- **Future runtime callbacks** — Any callback that is not documentation or monitoring triage is treated as requiring approval until explicitly added to the safe set.

---

## Trading / order / runtime / deploy are blocked by default

This is **intentional for safety**:

- **Trading and exchange** — Orders, execution, and exchange integration can move real funds; they must not run on a single “execute” without a human gate.
- **Order sync and lifecycle** — Bugs here can misrepresent portfolio or orders; changes should be approved.
- **Telegram command handling** — Can trigger user-facing or operational actions; approval required.
- **Infra runtime and deploy** — Restarts, nginx, docker-compose, and deploy logic affect production; approval required.

The first real callbacks are limited to **documentation** and **monitoring triage** (writing under `/docs` only). Expanding beyond that (e.g. narrow backend validation or code-changing apply) should either be added as new “safe” callbacks with explicit rules or stay behind the approval gate.

---

## How to use the gate

1. **Prepare with approval check**  
   Call `prepare_task_with_approval_check(project=..., type_filter=...)`. You get a bundle with `prepared_task`, `callback_selection`, `approval`, and `approval_summary`.

2. **Decide whether to execute**  
   - If `approval["required"]` is `False`: you may call `execute_prepared_task_if_approved(bundle, approved=False)` and execution will run (low-risk).  
   - If `approval["required"]` is `True`: do **not** execute until a human has agreed; then call `execute_prepared_task_if_approved(bundle, approved=True)`.

3. **Execution wrapper**  
   `execute_prepared_task_if_approved(prepared_bundle, approved=...)`:
   - If approval is required and `approved=False`: appends a Notion comment that execution is waiting for human approval and returns without running callbacks (task stays in-progress).
   - If approval is not required, or approval is required and `approved=True`: runs `execute_prepared_notion_task()` with the bundle’s callbacks.

### Version metadata effects

When version metadata is present in the prepared bundle:

- On proposal: `version_status=proposed`
- On approval: `version_status=approved` and `approved_version=proposed_version`
- On denial: `version_status=rejected`
- On successful execution/release: `version_status=released` and `released_version` is recorded

---

## Extended lifecycle (manual_only tasks)

Tasks with `manual_only=True` (e.g. bug investigation, strategy-patch) use an **extended lifecycle** with **two** human approval points:

1. **Investigation approval** — After OpenClaw analysis completes. The scheduler runs execution directly (no pre-execution approval); the first human touchpoint is this message.
2. **Deploy approval** — After patch validation passes, before deployment.

This reduces approval fatigue: the operator approves only when there is concrete analysis to review (investigation) and again before deploy. See [TELEGRAM_APPROVAL_UX_IMPROVEMENTS.md](TELEGRAM_APPROVAL_UX_IMPROVEMENTS.md).

---

## Telegram approval

Humans can approve or deny execution from Telegram.

- **Legacy flow:** After preparing a task with `prepare_task_with_approval_check()`, call `send_task_approval_request(prepared_bundle, chat_id)` to send a message with **Approve** / **Deny** / **View Summary** buttons. (This is skipped for `manual_only` tasks; they use the extended flow instead.)
- **Extended flow:** Approval messages are sent automatically at investigation-complete and before deploy.

Only authorized Telegram users may approve or deny; approval state is **persisted in the database** (`agent_approval_states`) and (on Approve) execution runs via the same executor. Pending approvals survive process restart. **Durable execution state** (execution_status, execution_started_at, executed_at) is stored in the same table to prevent duplicate execution from Telegram; retries are allowed when execution has failed. See [telegram-approval-flow.md](telegram-approval-flow.md).

For read-only visibility, authorized users can also open `/agent` in Telegram to inspect recent activity, pending approvals, and recent failure events without triggering new execution. See [telegram-agent-console.md](telegram-agent-console.md).

---

## Related

- [Callback selection](callback-selection.md) — Which task types get which callbacks.
- [Task execution flow](task-execution-flow.md) — Apply → testing → validate → deployed.
- [Telegram approval flow](telegram-approval-flow.md) — Approve/deny from chat; callback button format; DB-backed approval state.
- [Telegram agent console](telegram-agent-console.md) — Read-only activity, approvals, and failures from chat.
- Backend: `agent_approval.requires_human_approval`, `agent_approval.build_approval_summary`, `agent_task_executor.prepare_task_with_approval_check`, `agent_task_executor.execute_prepared_task_if_approved`, `agent_telegram_approval.send_task_approval_request`, `agent_telegram_approval.execute_prepared_task_from_telegram_decision`.
