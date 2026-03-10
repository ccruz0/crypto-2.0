# Bug investigations (agent)

Structured investigation notes for bug-type tasks. These are documentation-only and must not change runtime behavior.

Notes are created by the agent when applying bug-investigation tasks (e.g. from Notion). Each note is named `notion-bug-<task_id>.md`.

**Production (Docker):** Deploy scripts (`deploy_via_eice.sh`, `deploy_aws.sh`, `deploy_all.sh`) ensure this directory exists and is writable by the backend container (UID 10001) via `mkdir -p docs/agents/bug-investigations && sudo chown -R 10001:10001 docs/agents/bug-investigations`. No extra env is needed when using those deploys.

**Fallback when `docs/` is not writable:** If the backend runs where `docs/` is read-only or not chown’d, the agent uses a fallback directory. Set `AGENT_BUG_INVESTIGATIONS_DIR` to a writable path (e.g. `/tmp/agent-bug-investigations`) or leave unset to use that default. The same path is used for reads so validation and approval flows find the note.
