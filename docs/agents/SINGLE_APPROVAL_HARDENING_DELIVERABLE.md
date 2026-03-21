# Single-Approval Workflow Hardening — Deliverable

## Diff Summary

### agent_telegram_approval.py
- **DB-backed idempotency:** Added `_RELEASE_CANDIDATE_DEDUP_KEY_PREFIX`, `_RELEASE_CANDIDATE_DEDUP_HOURS` (7 days), `_release_candidate_approval_dedup_key()`, `_check_release_candidate_approval_dedup()`, `_get_release_candidate_approval_last_sent_db()`, `_set_release_candidate_approval_sent_db()`.
- **Fail-closed when DB unavailable:** `_check_release_candidate_approval_dedup` catches exceptions from `_get_release_candidate_approval_last_sent_db`; returns `(True, "dedup_check_unavailable")` → blocks send. `_get_release_candidate_approval_last_sent_db` now raises on DB error instead of returning `None`.
- **Mandatory proposed_version:** Empty or missing `proposed_version` blocks send; returns `skipped: "missing_proposed_version"`. No fallback to `_default`.
- **Dedup in _send_release_candidate_or_deploy_approval:** When `use_release_candidate_format=True`, uses DB-backed dedup with task_id + proposed_version. Records sent timestamp to DB after successful send.
- **Disabled legacy approval paths:** `send_ready_for_patch_approval` and `send_investigation_complete_approval` now return immediately with `skipped: "single_approval_workflow"` — no Telegram send.
- **Blocker wording:** `send_patch_not_applied_message` updated to include "(not an approval request)" and "exactly one final approval request when the release candidate is ready" to avoid confusion.

### agent_task_executor.py
- **proposed_version passed:** Both validation path and Cursor Bridge success path now pass `proposed_version` from task metadata to `send_release_candidate_approval` for correct dedup key.
- **No fallback on skipped:** Caller does not interpret `skipped` as a reason to trigger another approval path; only logs `tg.get("sent")` and `tg.get("message_id")`.

### test_notification_policy.py
- **TestReleaseCandidateApprovalBlocked:** `test_blocked_when_proposed_version_missing`, `test_blocked_when_dedup_check_unavailable`.
- **TestReleaseCandidateApprovalIdempotency:** `test_second_call_skipped_same_task_version`, `test_dedup_key_includes_version`.
- **TestSingleApprovalWorkflow:** `test_no_approval_during_investigation_patching_verification`, `test_one_final_approval_at_release_candidate_ready`, `test_new_version_allowed_new_approval`.
- **TestIntermediateApprovalDisabled:** `test_send_ready_for_patch_approval_returns_skipped`, `test_send_investigation_complete_approval_returns_skipped`.
- **TestPatchNotAppliedNoApprovalWording:** `test_patch_not_applied_says_not_approval_request`.

### verify_ready_for_patch_approval_flow.py
- Updated for single-approval workflow: traces `send_release_candidate_approval` at `release-candidate-ready`; dry run uses `send_release_candidate_approval` with `proposed_version`.

### docs/agents/
- **NOTIFICATION_POLICY_SINGLE_APPROVAL.md:** Added Idempotency section describing DB-backed dedup.
- **TELEGRAM_APPROVAL_UX_IMPROVEMENTS.md, TELEGRAM_APPROVAL_REDESIGN.md:** Updated for single-approval flow.

---

## Duplicate-Risk Paths Found

| Path | Risk | Mitigation |
|------|------|------------|
| **advance_ready_for_patch_task validation path** | Scheduler retries; task could run again after status already release-candidate-ready | `_resumable_statuses` = ("ready-for-patch", "patching") — task in release-candidate-ready is **not** picked. Dedup still blocks if any edge case. |
| **advance_ready_for_patch_task Cursor Bridge path** | Same task could run twice if CURSOR_BRIDGE_AUTO_IN_ADVANCE and handoff exist | Both paths share `send_release_candidate_approval` → same DB-backed dedup. |
| **agent_recovery revalidate_patching_playbook** | Retries stale patching tasks | Calls `advance_ready_for_patch_task`; dedup applies. |
| **Process restart** | In-memory `_DEPLOY_APPROVAL_SENT` lost; could send duplicate | Release-candidate uses **DB-backed** dedup (TradingSettings). |
| **Legacy send_ready_for_patch_approval** | If any code path still called it | **Disabled** — returns immediately without sending. |
| **Legacy send_investigation_complete_approval** | If any code path still called it | **Disabled** — returns immediately without sending. |
| **Legacy send_patch_deploy_approval** | Uses in-memory dedup only | Kept for backward compat; not used in main flow. |

---

## Idempotency Mechanism

- **Key:** `agent_release_candidate_approval:{task_id}:{proposed_version}`
- **Storage:** `TradingSettings` table (setting_key, setting_value)
- **Value:** ISO timestamp of last send
- **Cooldown:** 7 days (`_RELEASE_CANDIDATE_DEDUP_HOURS`)
- **Scope:** `send_release_candidate_approval` only (legacy `send_patch_deploy_approval` keeps in-memory dedup)
- **Behavior:** First send for a task+version → allowed. Second send within cooldown → skipped with `skipped: "dedup"` and no Telegram message.
- **Fail-closed:** If DB unavailable → `skipped: "dedup_check_unavailable"`; do not send.
- **Mandatory proposed_version:** If missing or empty → `skipped: "missing_proposed_version"`; do not send.
- **Dedup write failure:** `_set_release_candidate_approval_sent_db` returns `bool`; logs warning on failure. If send succeeds but write fails → add to `_SENT_BUT_DEDUP_WRITE_FAILED` (in-memory fallback); return `dedup_write_failed: True`; retry within same process blocked.

---

## Tests Added/Updated

| Test | Purpose |
|------|---------|
| `test_blocked_when_proposed_version_missing` | Verifies empty proposed_version blocks send |
| `test_blocked_when_dedup_check_unavailable` | Verifies DB error blocks send (fail-closed) |
| `test_second_call_skipped_same_task_version` | Verifies dedup skips second send for same task+version |
| `test_dedup_key_includes_version` | Verifies dedup key includes task_id and version |
| `test_no_approval_during_investigation_patching_verification` | Verifies intermediate states never send approval |
| `test_one_final_approval_at_release_candidate_ready` | Verifies first send succeeds, second (same task+version) deduped |
| `test_new_version_allowed_new_approval` | Verifies different version gets separate dedup key |
| `test_send_ready_for_patch_approval_returns_skipped` | Verifies intermediate approval disabled |
| `test_send_investigation_complete_approval_returns_skipped` | Verifies investigation approval disabled |
| `test_patch_not_applied_says_not_approval_request` | Verifies patch-not-applied message has no approval wording |
| `test_send_success_dedup_write_failure_returns_dedup_write_failed` | Send succeeds but dedup write fails → returns dedup_write_failed |
| `test_retry_after_dedup_write_failure_blocked_by_in_memory_fallback` | Retry after dedup write failure blocked; no duplicate send |

---

## Remaining Edge Cases

1. **TradingSettings DB unavailable:** Now **fail-closed** — `_get_release_candidate_approval_last_sent_db` raises; `_check_release_candidate_approval_dedup` catches and returns `(True, "dedup_check_unavailable")` → no send.

2. **Dedup marker write failure:** `_set_release_candidate_approval_sent_db` now returns `bool`; logs warning on failure. If send succeeds but write fails: (a) add (task_id, pv) to in-memory `_SENT_BUT_DEDUP_WRITE_FAILED`; (b) return `dedup_write_failed: True`; (c) retry within same process is blocked by in-memory fallback. **Process restart:** in-memory set is lost; duplicate possible. Surface `dedup_write_failed` for monitoring/alerting.

3. **proposed_version empty:** Now **blocked** — returns `skipped: "missing_proposed_version"`. Task compiler / metadata must provide `proposed_version` when advancing to release-candidate-ready.

4. **ready-for-deploy / awaiting-deploy-approval backward compat:** Tasks in these legacy states still pass deploy gate. They do **not** trigger a new approval send (only release-candidate-ready does). **Safe.**

5. **Notion status "Release Candidate Ready":** If Notion DB has no such option, backend can still set internal status; Notion may show "Unknown" or fallback. **Manual setup:** Add the option to Notion Status select.

6. **verify_ready_for_patch_approval_flow.py:** Updated for single-approval flow; dry run uses `send_release_candidate_approval` with `proposed_version`.
