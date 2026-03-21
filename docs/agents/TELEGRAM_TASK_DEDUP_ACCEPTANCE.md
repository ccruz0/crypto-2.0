# Telegram Task Deduplication — Acceptance Criteria & Validation

## 1. What Was Attempted

### Phase A: Never Reject Tasks (Impact Scoring)
- **Implemented:** Removed creation gate that rejected low-value tasks.
- **Implemented:** All tasks are created; low-impact get `status=backlog`, `priority=low`.
- **Implemented:** Removed execution gate in scheduler.
- **Status:** DONE (tests pass).

### Phase B: Merge New Input When Similar Task Exists
- **Implemented:** When `find_similar_task` returns an existing task:
  - Call `append_telegram_input_to_task(task_id, intent_text, user)` to persist new input.
  - Update priority in Notion.
  - Optionally move `planned` → `ready-for-investigation`.
  - Return `input_merged: True/False` in result.
- **Implemented:** Telegram response shows "Matched existing task" and "Your new instruction was added to the task history."
- **Implemented:** Observability: `similar_task_detected`, `telegram_input_merged_into_existing_task`, `notion_task_updated_from_telegram`, `telegram_input_dropped_after_match`.
- **Status:** Code complete; **end-to-end validation against real Notion not yet run**.

---

## 2. What Failed or Is Incomplete

| Item | Status | Risk |
|------|--------|------|
| Notion block append API | Uses `PATCH /blocks/{id}/children` | Notion API may expect `POST`; doc says PATCH — verify. |
| Integration capabilities | Notion integration needs "insert content" | 403 if missing. |
| Tasks in "Needs Revision" | Included in `ACTIVE_STATUSES_FOR_SIMILARITY` | Should be found for similarity. |
| Dry-run mode | `append_telegram_input_to_task` has no dry-run | In AGENT_DRY_RUN, append still hits Notion. |
| End-to-end test | No live Notion + Telegram test | May fail in production. |

---

## 3. Acceptance Criteria for DONE

- [ ] **AC1:** Send `/task <intent>` similar to existing task → no duplicate created.
- [ ] **AC2:** Existing Notion task page receives new block with merged Telegram input.
- [ ] **AC3:** Telegram reply: "Matched existing task" + "Your new instruction was added to the task history. Notion record updated."
- [ ] **AC4:** Logs contain `similar_task_detected`, `telegram_input_merged_into_existing_task`, `notion_task_updated_from_telegram`.
- [ ] **AC5:** When append fails: Telegram shows warning; `telegram_input_dropped_after_match` logged.
- [ ] **AC6:** Works for tasks in any active status (planned, needs-revision, investigating, etc.).

---

## 4. Proposed Fixes

### Fix 1: Add dry-run guard to `append_telegram_input_to_task`
When `AGENT_DRY_RUN` or `NOTION_DRY_RUN` is set, skip the Notion API call and return True (simulate success).

### Fix 2: Verify Notion API method
Confirm `PATCH /v1/blocks/{block_id}/children` is correct (Notion docs indicate PATCH).

### Fix 3: Add integration validation script
Script to test append against a real Notion page (optional; requires NOTION_API_KEY + test page ID).

---

## 5. Validation Checklist

1. **Automated validation:** `cd backend && PYTHONPATH=. python scripts/validate_telegram_task_dedup.py` — all pass.
2. **Unit tests:** `pytest backend/tests/test_task_compiler_similarity.py backend/tests/test_task_value_gate.py` — all pass.
3. **Manual Telegram test:** Send `/task Fix purchase_price discrepancy` when similar task exists → verify Notion page has new block.
4. **Log verification:** Check for `telegram_input_merged_into_existing_task` in logs.

---

## 6. Implementation Fixes Applied

| Fix | Status |
|-----|--------|
| Dry-run guard in `append_telegram_input_to_task` | DONE |
| Validation script `scripts/validate_telegram_task_dedup.py` | DONE |

---

## 7. DONE Criteria (All Must Pass)

- [x] AC1: No duplicate created when similar task exists (unit test)
- [x] AC2: New block appended to Notion task (code path; manual verification for live Notion)
- [x] AC3: Telegram reply shows "Matched existing task" + merge confirmation (code)
- [x] AC4: Observability events logged (code)
- [x] AC5: Append-failure path shows warning (unit test)
- [x] AC6: Works for needs-revision and other active statuses (ACTIVE_STATUSES_FOR_SIMILARITY includes them)
- [x] Automated validation script passes
- [ ] **Manual:** Send similar `/task` via Telegram → confirm Notion page updated (operator verification)
