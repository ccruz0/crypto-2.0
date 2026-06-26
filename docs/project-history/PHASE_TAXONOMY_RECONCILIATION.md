# Phase Taxonomy Reconciliation

> **Purpose:** Reconcile the two phase taxonomies that govern Jarvis/ACW work so
> implementers never have to guess which "Phase N" a task belongs to.
>
> - **External roadmap (risk-class taxonomy):** Phases 1–8, organized by security
>   risk class (read → sandbox-write → external-write → orchestration).
> - **Repo plan (mode taxonomy):** `JARVIS_CONTROL_CENTER_IMPLEMENTATION_PLAN.md`,
>   organized by operating mode (Advisor / Builder / Operator).
>
> These two taxonomies have lived in different places — the roadmap external to the
> repo, the mode plan inside it. That separation is exactly the condition that
> produces "I thought Phase 3 was the other thing" errors. This document puts the
> reconciliation where the implementers live.
>
> **Status:** Read-only validation artifact. Every code claim below was verified
> against the repository at the stated commit. This document does not change code.
>
> **Evidence basis:** repo `main` @ `a0eb7878480774226003f99b372a03826ca0935a`.
> File:line references point at the verifying evidence.

---

## 0. The two taxonomies (one-liners)

### External roadmap — Phases 1–8 (risk class)

| Phase | Capability |
|-------|------------|
| **1 — MCP Core** | Read-only opening: transport mTLS, authN/authZ default-deny, registry loader fail-closed, audit pipeline. Zero write executors. |
| **2 — Identity Broker** | Ephemeral, role-scoped agent identity issuance (mTLS cert + signed token). |
| **3 — Approval Authority** | Human approval as prerequisite for a privileged token; **includes migrating the in-memory approval storage (A8) to durable**. |
| **4 — Read tools S2** | `read_git_status` + `read_system_health` end-to-end over the core. |
| **5 — Rest of read tools** | logs (with redaction + tripwire), repository, runtime_flags, alerts, prs, scheduler, db_metrics. |
| **6 — Sandbox tooling** | `SANDBOX_WRITE`, Gate 1, LAB: apply/test in sandbox; **includes the cursor-auth merge fix (A6) as 6.1**. |
| **7 — PR creation** | `EXTERNAL_WRITE`, Gate 2, LAB: `create_pr` after human approval; never merge/deploy. |
| **8 — Supervisor orchestration** | Deterministic loop (decomposition, per-phase allow-list, CostGuard, task memory); **includes the Bedrock decision layer — tool-use + wiring to CostGuard (A4/A10)**. |

### Repo plan — Advisor / Builder / Operator (operating mode)

| Mode (plan phase) | Capability | PROD (`ATP_TRADING_ONLY=1`) | LAB |
|-------------------|------------|------------------------------|-----|
| **Advisor (P1)** | Read-only analysis; read-only tools; `dry_run` forced `true`. | Yes | Yes |
| **Builder (P2)** | Staging git, diff, tests, PR draft; delegates to `cursor_execution_bridge` + `repo_worker_mvp`; **no deploy**. | **No** | Yes |
| **Operator (P3)** | Approved mutations, SSM, deploy, config writes; governance manifest. | **No** (until explicit operator flag) | Yes (first) |

Source: `docs/architecture/JARVIS_CONTROL_CENTER_IMPLEMENTATION_PLAN.md` §5, §7.1, App.

---

## 1. Correspondence table (verified, not inferred)

Each cell is fixed against both sides; the final column is the **actual state in code today**.

| External phase | Capability | Repo counterpart | Relation | In code today? |
|----------------|------------|------------------|----------|----------------|
| **1 — MCP Core** | transport mTLS, authz default-deny, registry fail-closed, audit | — (none) | **gap** — repo assumes the infra | not a repo phase |
| **2 — Identity Broker** | ephemeral role-scoped agent identity | — (none) | **gap** | n/a |
| **3 — Approval Authority** | human approval → privileged token; + A8 durability | partial: `jarvis_control_approvals` tables + `/builder/.../approve`/`reject` endpoints | **partial overlap** | endpoints exist; **store is in-memory (A8)** — durability missing |
| **4 — Read tools S2** (`read_git_status`, `read_system_health`) | core read tools | **Advisor (P1)** read-only tools | **subset of Advisor** | Advisor **not implemented** (doc/stub) |
| **5 — Rest of read tools** (logs+redaction, repo, flags, alerts, prs, scheduler, db) | extended read tools | **Advisor (P1)** context/domain | **subset of Advisor** | same (not implemented) |
| **6 — Sandbox tooling** (Gate 1, LAB) + **cursor-auth 6.1** | apply/test in sandbox | **Builder (P2)** prepare/diff/tests | **Builder ⊇ Phase 6** | `/builder/*` stub exists; `cursor_execution_bridge` exists; **`coding_workflow` merge incomplete (A6)** |
| **7 — PR creation** (Gate 2, LAB) | `create_pr`, never merge/deploy | **Builder (P2)** open-pr | **Builder ⊇ Phase 7** | `create_pull_request` exists; `FORBIDDEN_ACTIONS` blocks merge/deploy |
| **8 — Supervisor + decision layer** (A4/A10) | deterministic loop + Bedrock tool-use + CostGuard | — (planner in `jarvis/mvp`, not a phase) | **gap** | CostGuard exists (A10); `ask_bedrock` **has no tool-use** (A4) |
| **(invariant frontier)** | — | **Operator (P3)**: mutations / SSM / deploy / config | **splits across the invariant** → §2 | **Operator does not exist in code** |

### Two confirmed asymmetries

- **Builder (repo P2) = external Phases 5 + 6 + 7.** The repo groups "everything the
  builder does" into one mode; the external roadmap separates read / sandbox-write /
  PR by **risk class**. Builder is a **superset** of three external phases.
- **External Phases 1, 2, 8 and half of 3 have no repo phase.** MCP Core, Identity
  Broker, the decision layer, and durability are infrastructure the repo plan takes
  for granted or places in new `jarvis_control_*` tables without treating it as a phase.

Advisor (repo P1) ≈ the external read base (Phases 4–5), and is itself **not yet
implemented** — see §3.

---

## 2. Operator decomposition against the HUMAN_ONLY invariant

The repo's Operator mode bundles capabilities that, in the external risk-class model,
fall on **both sides** of a frozen invariant. Reconciling Operator is not cosmetic — it
is deciding, per capability, which side of the invariant it lands on. Because the
deploy/SSM/config capabilities are **unimplemented today**, this frontier can be fixed
in *design* before any code forces it after the fact.

| Repo Operator capability | External side | Agent executor? | Code status today |
|--------------------------|---------------|-----------------|-------------------|
| Approved file mutations (apply) | **Phase 6** (`SANDBOX_WRITE`, Gate 1, LAB) | **Yes** (sandbox, LAB) | bridge exists; merge incomplete (A6) |
| PR creation | **Phase 7** (`EXTERNAL_WRITE`, Gate 2, LAB) | **Yes** (LAB, post-approval) | `pr_service.create_pull_request` exists |
| **Merge** | **HUMAN_ONLY** (invariant #1) | **No** | `FORBIDDEN_ACTIONS` denies |
| **Deploy / SSM** | **HUMAN_ONLY** (invariant #2; a Deployment Agent may only *prepare* / *request*) | **No** | not implemented; `FORBIDDEN_ACTIONS` denies `deploy`; real deploy = SSM workflow, human/CI |
| **Config writes (prod)** | **HUMAN_ONLY** (governance-gated) | **No** | not implemented |

**Conclusion:** Operator does **not** map to a single external phase. It maps to
*"Phases 6–7 (the agent-executor part) + the HUMAN_ONLY frontier (the part with no
executor)."*

### Deployment Agent reconciliation note

The infrastructure mandate's "Deployment Agent" brushes against invariants #1–#2. It
may **prepare** a release, **generate** a rollback plan, and **request** a human-gated
deploy — but it must not hold a deploy/merge executor. Those remain HUMAN_ONLY with no
agent-side executable path.

---

## 3. Barriers documented but NOT implemented (read before touching Operator)

This is the load-bearing section. The correspondence table is the map; this list is the
**warning**: guarantees the design assumes that do not yet exist in code. An implementer
must see this before assuming any of them holds.

### 3.1 Operator is not implementable until its gate lands in the same change

Verified: `routes_jarvis_control.py` is self-described as *"read-only status, task
visibility, Builder prepare **stub**"* and exposes only `/status` and `/builder/*` — no
`/operator/run`, no SSM, no deploy, no config-write endpoint anywhere. The HUMAN_ONLY
frontier is held today by **the absence of the route itself**, plus four real layers:

1. **No Operator code exists.**
2. `JARVIS_CONTROL_ENABLED` unset → false in prod → the control router is **not mounted**
   (`factory.py:946-947`, gated by `is_jarvis_control_enabled()`).
3. `ATP_TRADING_ONLY=1` in prod (via `docker-compose.yml:218` `${ATP_TRADING_ONLY:-1}`,
   confirmed in the live container env) → automation/governance routers unmounted and
   Builder blocked per-route.
4. `FORBIDDEN_ACTIONS = {merge, close_pr, deploy, push_to_main, force_push, delete_branch}`
   (`backend/app/jarvis/github/pr_service.py`) as a code-level backstop.

**The risk is forward-looking, not present.** The missing `JARVIS_OPERATOR_ALLOWED` gate
is moot today because there is no Operator code to gate. But the moment Operator is built,
layer (1) disappears; if its gate is not implemented **in the same PR**, you are left with
three layers where the design promised four.

> **Rule:** Operator cannot land a single line without its gate landing in the same change.

### 3.2 Doc-only flags/projections (status verified in code)

| Item | Status | Implication |
|------|--------|-------------|
| `JARVIS_OPERATOR_ALLOWED` | **doc-only (absent in code)** | Moot today (no Operator code to gate), but becomes the missing layer the instant Operator lands — must ship in the same PR (see §3.1), never inherited. |
| `JARVIS_PROD_TRADING_OPERATOR` | **doc-only** | break-glass not implemented. |
| `JARVIS_DEPLOY_DUAL_APPROVAL` | **doc-only** | the dual-approval the plan promises for prod deploy does not exist. |
| `A5 → jarvis_control_tasks.status` projection | **undefined** | see §3.3 — must be a documented many-to-one map. |
| `FORBIDDEN_ACTIONS` backstop | **implemented** — must not be weakened | the only code layer that survives once Operator exists. |

For contrast, these governing flags **are** implemented and were verified:
`JARVIS_CONTROL_ENABLED` (`routes_jarvis_control.py`), `JARVIS_BUILDER_ALLOWED`
(`environment.py`, `routes_jarvis_control.py`), `ATP_GOVERNANCE_AGENT_ENFORCE`
(`agent_execution_policy.py`), `JARVIS_DRY_RUN_ONLY` (`inspect_runtime.py`).

### 3.3 Lifecycle projection (no 1:1 — preserve the two gates)

The repo plan uses its own status vocabulary, in two levels:

- `jarvis_control_tasks.status`: `queued, planning, running, awaiting_approval, completed, failed, cancelled`
- `jarvis_control_actions.status`: `pending, approved, rejected, executing, completed, failed, skipped`

The orchestrator's `execution/lifecycle.py` (A5) uses a different, finer set:
`patch_ready, waiting_for_approval, waiting_for_pr_approval, pr_created, completed, failed, insufficient_evidence, cancelled`.

These are **not interchangeable**. The plan's single `awaiting_approval` **collapses** the
two gates that A5 separates: `waiting_for_approval` (apply, Gate 1) and
`waiting_for_pr_approval` (PR, Gate 2). In the Approval Authority model, Gate 1 and Gate 2
are **distinct approvals, with distinct bindings, consumed separately** — that separation
is the very security property double-approval exists to guarantee.

**Resolution:** A5 is the *execution detail of Builder mode*; the plan's `status` is a
*coarse task/UI rollup*. Do not pick one. Define an explicit, documented **many-to-one
projection `A5 → jarvis_control_tasks.status`** so the two A5 gates remain two real
approvals even when the UI shows a single `awaiting_approval`. Two state machines on the
same path without a declared projection = guaranteed desync.

---

## 4. The HUMAN_ONLY frontier (declared explicitly)

Declared now, while it is still a design decision rather than archaeology. The following
capabilities have **no agent-side executable path** — no agent executor, in any phase,
under any flag combination:

- **Deploy** (to any environment) — agent may *prepare*/*request*; the executable path is
  the SSM deploy workflow run by a human/CI (`.github/workflows/deploy_session_manager.yml`).
- **SSM command execution** against hosts.
- **Merge** of any PR (agent creates PRs in Phase 7; merge is human).
- **Production config writes** (including `ATP_TRADING_ONLY` env changes).

**Justification:** these map to frozen Dossier invariants #1–#2 (no deploy/merge
executor). They are enforced today by `FORBIDDEN_ACTIONS` (code), by the SSM-only deploy
path, and by the absence of any Operator route. The invariant must hold structurally: no
future flag (`JARVIS_OPERATOR_ALLOWED`, `JARVIS_PROD_TRADING_OPERATOR`, etc.) may open an
agent-side executable path to any item above. Those flags may gate *preparation* and
*requesting*, never *execution*.

This is the same principle applied to staging isolation and to the `--trust` flag: decide
the security property while it is still a decision. (Those two implementation-level
guarantees are tracked in the Phase 6.1 acceptance criteria, not here.)
