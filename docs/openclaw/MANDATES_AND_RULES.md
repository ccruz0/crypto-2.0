# OpenClaw — Mandates and Operational Rules

Use the UI at **/openclaw** (or https://dashboard.hilovivo.com/openclaw/) to run mandates. Before heavy use: run a **calibration mandate** (read-only), then apply operational rules to control cost and risk.

---

## Calibration mandate (safe, first run)

Run this first to verify quality and that no files are modified:

```
Analyze the repository structure and produce a system architecture map without modifying any files.
```

**Pass criteria:** OpenClaw returns an analysis/map and does not create branches, PRs, or file changes.

---

## Mandate #1 – Trading Execution Reliability (LAB)

Paste the following into OpenClaw (branch: **develop** only; PRs to develop, never to main).

```
MANDATE #1 — Trading Execution Reliability (LAB)

Mission
Audit and harden the order execution layer for reliability and safety.
Do not change strategy logic or trading parameters.
Goal is operational robustness: correct orders, correct state, correct logging.

Scope (ONLY)
- Crypto.com Exchange API execution layer (create/cancel/replace/query)
- Order lifecycle + state transitions (PLACED, PURCHASED, SOLD, UPDATED)
- Idempotency / duplicate prevention
- Retry policy, backoff, timeouts
- Crash recovery and reconciliation (exchange vs sheet)
- Google Sheets write consistency and error handling

Out of scope (DO NOT TOUCH)
- Signal generation / indicators / strategy thresholds
- CPI bot logic
- Capital allocation rules
- Telegram copy/formatting (unless needed to add a single critical alert for execution failures)
- Infrastructure, Docker, Nginx, CI rules, branch protections
- Secrets, tokens, credential handling

Operating mode
- Start read-only: analysis and reporting first.
- Then minimal patches with small, isolated diffs.
- Work ONLY on branch: develop
- Output ONLY as PRs to develop (never push to main).

Deliverables
1) Execution Audit Report (markdown)
   - Map the exact execution flow (functions/files, call chain).
   - List concrete failure modes:
     - duplicate order risk
     - orphan order risk
     - partial fill handling risk
     - inconsistent state between exchange and sheet
     - race conditions / concurrent runs
     - rate-limit / timeout behavior
   - For each risk: severity + how to reproduce + where it happens.

2) Reliability Upgrade Plan (prioritized)
   - 5–10 specific upgrades, each with:
     - problem solved
     - minimal change approach
     - expected impact
     - any tradeoffs
   - Must include:
     - idempotency design (keying strategy)
     - retry policy (backoff + jitter + max attempts)
     - reconciliation loop (source of truth rules)
     - safe handling of 429/5xx and network errors

3) Patch Set (minimal, auditable)
   - PR #1: logging + correlation IDs (no behavior change)
   - PR #2: idempotency + duplicate prevention
   - PR #3: reconciliation & crash recovery (if feasible without large refactor)
   - Each PR includes tests or a deterministic "dry-run" validation mode.

Quality bar
- No sweeping refactors.
- Every change must be easy to review.
- Never print secrets or headers like Authorization.
- Any new logs must redact tokens.

Stop conditions
If you discover a critical risk that could place real orders incorrectly, stop and report immediately before coding.
```

---

## OpenClaw operation rules (LAB)

**1) Branch discipline**
- Work only on **develop**.
- PRs only. No direct commits to **main**.

**2) Safety**
- Never modify strategy or trading parameters unless explicitly mandated.
- Never touch secrets, tokens, credential files, or auth flows.
- Never log Authorization headers or token-like strings.

**3) Scope control**
- If a requested change touches infra/CI/Docker, stop and ask for explicit approval.
- Keep diffs small and isolated.

**4) Output format**
- Every run must end with:
  - a short report (what you found)
  - a list of proposed upgrades (prioritized)
  - links to PRs (if any)

**5) Cost control**
- Prefer static analysis before running heavy tests.
- Avoid long loops or broad “scan everything” runs unless asked.

---

## Where to run

1. Open **https://dashboard.hilovivo.com/openclaw** (or /openclaw in the dashboard).
2. Authenticate with Basic Auth if prompted.
3. Paste the calibration mandate or Mandate #1 into the UI and run.
