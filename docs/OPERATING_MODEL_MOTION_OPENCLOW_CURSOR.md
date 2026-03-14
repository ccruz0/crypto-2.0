# Motion / OpenClaw / Cursor Operating Model

## 1. Purpose

This document defines the workflow between **Motion** (task management and prioritization), **OpenClaw** (technical analysis and change planning), and **Cursor** (code implementation) to safely evolve the Automated Trading Platform. The operating model ensures that changes are sequenced, analyzed, and implemented in a controlled way, with clear handoffs, verification, and rollback paths.

## 2. Roles of Each System

### Motion

Motion manages:

- **Task prioritization** — what gets done first
- **Sequencing** — order of work items
- **Deadlines** — when work is due
- **Dependencies** — blockers and prerequisites
- **Ownership** — who is responsible
- **Project visibility** — status and progress

Motion answers: **"What should be done next?"**

### OpenClaw

OpenClaw performs:

- **Repository analysis** — understanding codebase structure and behavior
- **Architecture understanding** — how components interact
- **Risk analysis** — impact and failure modes
- **Change planning** — minimal, targeted changes
- **Generation of Cursor prompts** — ready-to-use instructions for implementation

OpenClaw answers: **"What exactly should change and how?"**

### Cursor

Cursor performs:

- **Scoped code changes** — edits limited to the agreed scope
- **Documentation updates** — runbooks, READMEs, design docs
- **Script modifications** — when approved and specified
- **Infrastructure adjustments** — only when explicitly approved

Cursor answers: **"Apply the approved change safely."**

## 3. Task Lifecycle

The complete lifecycle for a change is:

1. **Motion task created** — Task is defined with objective, area, priority, and verification criteria.
2. **Motion task approved for analysis** — Task is marked ready for technical analysis.
3. **OpenClaw analyzes the repo** — OpenClaw inspects relevant areas, dependencies, and risks.
4. **OpenClaw produces:**
   - **Findings** — what was found (duplicates, gaps, inconsistencies)
   - **Implementation plan** — minimal steps to achieve the objective
   - **Cursor prompt** — precise instructions for Cursor
   - **Verification steps** — how to confirm success
   - **Rollback steps** — how to revert if needed
5. **Cursor implements the scoped change** — Only the agreed files and behavior are modified.
6. **Verification runs** — Operator or automation runs the verification steps.
7. **Motion task marked complete** — After verification passes and documentation is updated.

## 4. Task Template (Motion)

Motion tasks must include these fields:

| Field | Description |
|-------|-------------|
| **Title** | Short, descriptive name |
| **Objective** | What success looks like |
| **System Area** | infra / backend / monitoring / trading logic |
| **Priority** | Relative importance and urgency |
| **Dependencies** | Other tasks or systems that must be in place first |
| **Risk Level** | Low / Medium / High |
| **Requested Output** | analysis / implementation / audit |
| **Verification Criteria** | How we know the task is done correctly |
| **Rollback Notes** | High-level rollback approach |

## 5. OpenClaw Analysis Output

OpenClaw outputs must include:

- **Repository areas inspected** — paths, services, or components analyzed
- **Relevant files/scripts/services** — list of artifacts that matter for the change
- **Risk analysis** — what could go wrong and mitigation
- **Minimal change plan** — step-by-step, smallest necessary changes
- **Cursor prompt** — full, copy-pasteable prompt for Cursor
- **Verification commands** — exact commands to run and expected outputs
- **Rollback instructions** — commands or steps to revert

## 6. Cursor Implementation Rules

Cursor must follow these rules:

- **Modify only the scoped files** — no edits outside the agreed scope
- **Keep unrelated logic untouched** — avoid side effects in other areas
- **Preserve backwards compatibility** — no breaking changes unless explicitly approved
- **Avoid large refactors** — prefer small, incremental changes
- **Update documentation if behavior changes** — runbooks, READMEs, and design docs stay in sync
- **Provide a change summary** — what was changed and where, for handoff and review

## 7. Verification Standard

Each implementation must include:

- **Operational verification commands** — what to run (e.g. health checks, smoke tests)
- **Expected outputs** — what “good” looks like
- **Health checks** — relevant endpoints or metrics to confirm system health
- **Rollback command if failure occurs** — single command or short procedure to revert

## 8. Safety Principles

Key safety principles for the platform:

- **One change at a time** — avoid batching unrelated changes; isolate impact
- **No broad refactors in production systems** — prefer targeted fixes and incremental improvement
- **Observability before automation** — ensure we can see state and failures before adding automation
- **Documentation before removal** — document what exists and how to recover before removing or replacing
- **Verification before consolidation** — confirm each piece works before merging or consolidating behavior

## 9. Example Workflow

**Example task:** *"Review duplicate health recovery mechanisms"*

1. **Motion creates task** — Title, objective (audit and consolidate), system area (monitoring), requested output (audit + consolidation plan).
2. **OpenClaw audits repo** — Finds health_monitor.service, swap/EC2 recovery, ATP timers, and documents overlap and ownership.
3. **OpenClaw produces consolidation plan** — Which layer does what, what to keep/remove, and a runbook for operators.
4. **Cursor prepares runbook** — Writes or updates the runbook (e.g. `PROD_HEALTH_MONITOR_FIRST_CONSOLIDATION_RUNBOOK.md`) with steps, verification, and rollback.
5. **Operator executes runbook** — Performs consolidation in production when ready; verification and Motion update complete the task.

## 10. Definition of Done

A task is complete only when:

- **Change implemented** — Code, config, or runbook changes are in place as specified
- **Verification successful** — Verification commands have been run and passed
- **Rollback path documented** — Rollback steps are written and reviewable
- **Motion updated** — Task status and any notes are updated in Motion
- **Documentation updated** — Relevant docs (runbooks, READMEs, operating model) reflect the new state

## 11. Current System Baseline

Summary of the current production layers (as of the operating model baseline):

- **Infrastructure recovery (AWS EC2)** — EC2 auto-recovery and related AWS mechanisms handle instance-level failures.
- **OS stability (swap)** — Swap configuration and safety margin are in place to reduce OOM risk and improve OS stability.
- **Container runtime (Docker)** — Application runs in containers; Docker and compose are the runtime layer (no changes from this operating model).
- **Application monitoring (ATP timers)** — Platform-specific timers and jobs provide application-level health and recovery; no separate `health_monitor.service` on PROD.
- **External health endpoint (/api/health)** — External consumers use the API health endpoint for liveness and readiness.

This baseline is the reference for “what exists” when OpenClaw analyzes and Cursor implements; changes that affect it must be documented and verified per this operating model.
