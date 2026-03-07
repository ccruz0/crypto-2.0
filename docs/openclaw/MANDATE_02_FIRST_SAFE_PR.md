# Mandate #2: First Safe PR for Trading Platform Stability

Pegar este texto en la UI de OpenClaw después del Mandate #1 (auditoría). Objetivo: una primera PR pequeña y segura con impacto real.

---

## Goal

- Produce one small pull request that reduces real production risk without changing trading strategy logic.

## Scope

- **Repo:** automated-trading-platform
- **Focus only on:** safety + correctness guards in Telegram command processing and state handling.

## Non-goals

- No changes to signal logic, entry/exit strategy, indicators, or risk model math.
- No changes to exchange execution logic beyond safety checks.
- No UI work.

## Rules

- You may edit files and create a PR.
- Do not add any logging that can leak secrets.
- Do not print env vars, tokens, headers, or credential helpers.
- Changes must be minimal and well-scoped.

## Work plan

1. Identify the top 1–2 instability risks in Telegram handling that can cause duplicate actions or state flips.
2. Implement a minimal fix with tests or a deterministic reproduction harness.
3. Add a short "How to verify" section in the PR description with exact commands.

## Acceptance criteria

- No duplicate command execution when:
  - Telegram polling overlaps (multiple processes)
  - Callback query repeats
  - Message edits vs new messages occur
- No regression in normal menu navigation.
- Logs remain free of secrets.
- Lint/type checks still pass.

## Files to start from

- `backend/app/services/telegram_commands.py`
- `backend/app/models/telegram_state.py`
- `backend/app/models/watchlist.py`
- Any service that triggers orders from Telegram actions

## Deliverables

- One PR with:
  - A clear title: **"Telegram: prevent duplicate command execution and stabilize state updates"**
  - Small diff
  - Tests or a reproducible script (even if minimal)
  - Before/after explanation

## Suggested concrete target for this PR

- Replace in-memory dedupe (global dict TTL) with **DB-backed dedupe** keyed by:
  - `chat_id + message_id + command text` (or `callback_query.id`)
  - plus a short TTL window
- This survives restarts and prevents multi-instance duplication.

---

## Stop condition

**If OpenClaw finds that the highest real risk is not in Telegram but elsewhere** (e.g. order lifecycle, SL/TP placement, exchange reconciliation):

- Do **not** force the PR into Telegram scope.
- Instead: produce a short **"Mandate #2 pivot" note** with:
  1. Where the real risk was found (file paths + function names).
  2. Why that risk is higher than Telegram dedupe for this PR.
  3. A minimal, safe change set for *that* area (still one small PR) **or** a recommendation to do Mandate #2b focused on that area first.
- Then either deliver the pivot PR or hand off the checklist below for the chosen area.

---

## Verification checklist (exact commands)

### Local

```bash
# From repo root
cd backend
python -m pytest app/tests/ -v -k telegram 2>/dev/null || python -m pytest app/tests/ -v --ignore=app/tests/e2e 2>/dev/null | head -80

# Lint/type (adjust to project)
ruff check app/services/telegram_commands.py 2>/dev/null || true
mypy app/services/telegram_commands.py --no-error-summary 2>/dev/null | head -20
```

### Prod (after merge; read-only checks)

```bash
# No duplicate handling: trigger same callback twice in < TTL, second must be no-op or idempotent
# 1. Open Telegram bot, open menu that triggers a state-changing action (e.g. toggle watchlist).
# 2. Tap the same button twice quickly (or send same command twice).
# 3. Expect: only one state change; logs show dedupe or single execution.

# Logs must not contain secrets
grep -E "token|secret|password|api_key|Authorization" /path/to/app/logs/*.log 2>/dev/null | grep -v "REDACTED" && echo "FAIL: possible secret in logs" || echo "OK: no raw secrets in logs"
```

*(Ajustar rutas de logs según el despliegue.)*

---

## PR description template

```markdown
## Title
Telegram: prevent duplicate command execution and stabilize state updates

## Problem
[1–2 sentences: e.g. in-memory dedupe is lost on restart; multiple polling processes can double-execute.]

## Solution
[1–2 sentences: e.g. DB-backed dedupe keyed by chat_id + message_id + command/callback_id with TTL.]

## How to verify
- **Local:** [exact pytest or script command]
- **Manual:** Send same Telegram command/callback twice within TTL; second must be no-op or idempotent.
- **Logs:** No env vars, tokens, or credentials in new log lines.

## Scope
- No strategy or exchange execution logic changed.
- Lint/type: [paste output of ruff/mypy or project check].
```

---

*Si quieres este mandato aún más operable, se puede añadir un script de repro mínimo (e.g. `scripts/openclaw/repro_telegram_dedup.py`) que simule doble callback y compruebe idempotencia.*
