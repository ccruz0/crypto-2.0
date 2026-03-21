# Bug investigations (agent)

Structured investigation notes for bug-type tasks. These are documentation-only and must not change runtime behavior.

Notes are created by the agent when applying bug-investigation tasks (e.g. from Notion). Each note is named `notion-bug-<task_id>.md`.

**Production (Docker):** Deploy scripts (`deploy_via_eice.sh`, `deploy_aws.sh`, `deploy_all.sh`) ensure this directory exists and is writable by the backend container (UID 10001) via `mkdir -p docs/agents/bug-investigations && sudo chown -R 10001:10001 docs/agents/bug-investigations`. No extra env is needed when using those deploys.

**Fallback when `docs/` is not writable:** If the backend runs where `docs/` is read-only or not chown’d, the agent uses a fallback directory. Set `AGENT_BUG_INVESTIGATIONS_DIR` to a writable path (e.g. `/tmp/agent-bug-investigations`) or leave unset to use that default. The same path is used for reads, validation, approval flows, and recovery (missing-artifact playbook), so artifacts are always found regardless of where they were written.
- [Notion bug 6c800cf6-1ad1-4b51-bbed-56f2b4980aad: E2E flow test: add runbook link to README](notion-bug-6c800cf6-1ad1-4b51-bbed-56f2b4980aad.md)
- [Notion bug 4d7d1312-8ece-4fcb-b092-ef437c09ee2c: Investigate why Telegram alerts are not sent when buy or sell conditions trigger](notion-bug-4d7d1312-8ece-4fcb-b092-ef437c09ee2c.md)
- [Notion bug 31db1837-03fe-80d7-bf88-d802134064ad: Investigate duplicate signal alert generation after monitoring cycle](notion-bug-31db1837-03fe-80d7-bf88-d802134064ad.md)
- [Notion bug 10d75276-fcff-48bc-b5c9-473dec72bebd: RESET: purchase_price becomes null/missing — prove exact failure point (code + data flow)](notion-bug-10d75276-fcff-48bc-b5c9-473dec72bebd.md)
- [Notion bug 1df2868f-7a3f-4013-8820-2b0e92109221: Audit BTC Alert Spam and Alert Rules Compliance](notion-bug-1df2868f-7a3f-4013-8820-2b0e92109221.md)
- [Notion bug 24b4bb07-2ab3-43e0-aa05-d7c18f0b4773: Fix purchase_price discrepancy across trading system](notion-bug-24b4bb07-2ab3-43e0-aa05-d7c18f0b4773.md)
- [Notion bug 31cb1837-03fe-8045-b8a8-e27cca1198e0: Open orders not appearing in dashboard](notion-bug-31cb1837-03fe-8045-b8a8-e27cca1198e0.md)
