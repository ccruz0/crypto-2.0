# Secrets and runtime.env runbook

**No secret values are shown in this document. Variable names only.**

## Where runtime.env is created

- **Script:** `scripts/aws/render_runtime_env.sh`
- **Output file:** `secrets/runtime.env` (in repo root)
- **When:** Run before any `docker compose --profile aws` deploy. Deploy scripts (`scripts/deploy_aws.sh`, `scripts/aws/aws_up_backend.sh`) call it and abort if the file is missing.

## Variables that live in runtime.env (names only)

Rendered by `render_runtime_env.sh`:

- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- ADMIN_ACTIONS_KEY
- DIAGNOSTICS_API_KEY
- ENVIRONMENT
- RUN_TELEGRAM

**Rendered by `render_runtime_env.sh` (cost optimization):**

- OPENCLAW_VERIFICATION_PRIMARY_MODEL — Uses cheap model for verification (PASS/FAIL). Set to `openai/gpt-4o-mini` by default. Add OPENCLAW_API_TOKEN and OPENCLAW_API_URL manually if using OpenClaw.

**Rendered by `render_runtime_env.sh` (Notion / AI Task System):**

- NOTION_API_KEY — Notion integration token. Fetched from SSM (prod `/automated-trading-platform/prod/notion/api_key` or LAB `/automated-trading-platform/lab/notion/api_key`) when available, or from `.env.aws` (fallback). On LAB, render tries LAB SSM automatically so no manual secret insertion is required if the parameter exists.
- NOTION_TASK_DB — Notion database ID. SSM `/automated-trading-platform/prod/notion/task_db` or `.env.aws`. On LAB, if only the API key is in SSM, a default DB ID is used. Example: `eb90cfa139f94724a8b476315908510a`. See [NOTION_TASK_TO_CURSOR_AND_DEPLOY.md](NOTION_TASK_TO_CURSOR_AND_DEPLOY.md) § Task stuck in Planned.

**Source:** AWS SSM (prod, then LAB for Notion) or `.env.aws` (fallback). Do not change secret sources unless necessary.

## Where the Notion secret and database ID are stored

| What | Local (e.g. your Mac) | Server (e.g. EC2 PROD) |
|------|------------------------|--------------------------|
| **NOTION_API_KEY** (integration token / secret) | `backend/.env` — used when you run `./scripts/run_notion_task_pickup.sh` or the backend locally. Add it via the popup (`./scripts/notion_secret_popup.sh`) or the HTML helper (`scripts/notion_secret_prompt.html`), or paste the line into `backend/.env`. **Do not commit** `backend/.env`. | `secrets/runtime.env` — add manually (e.g. `NOTION_API_KEY=ntn_...`). The backend container and pickup script read it from here. **Do not commit** `secrets/runtime.env`. |
| **NOTION_TASK_DB** (database ID, not a secret) | Passed as env when running the pickup script, e.g. `NOTION_TASK_DB=eb90cfa139f94724a8b476315908510a ./scripts/run_notion_task_pickup.sh`, or set in `backend/.env` or `secrets/runtime.env` so the scheduler uses the correct database. | `secrets/runtime.env` — e.g. `NOTION_TASK_DB=eb90cfa139f94724a8b476315908510a`. Optional: can be passed per run via `-e NOTION_TASK_DB=...` when using `docker compose exec`. |

**Summary:** The Notion **secret** (API key) is in `backend/.env` locally and in `secrets/runtime.env` on the server (rendered by `render_runtime_env.sh` from SSM or `.env.aws`). The Notion **database ID** (`NOTION_TASK_DB`) is rendered the same way. Neither file should be committed to git.

### Verify Notion in backend-aws (LAB or EC2)

**Diagnostic (no secrets printed):**  
`./scripts/diagnostics/check_notion_env.sh` — reports NOTION_API_KEY and NOTION_TASK_DB present/missing and source (SSM, .env.aws, runtime.env, container).

**LAB auto-repair (no manual keys):**  
If Notion env is missing on LAB and the SSM parameter `/automated-trading-platform/lab/notion/api_key` exists, run on the LAB host:  
`./scripts/aws/fix_notion_env_lab.sh` — fetches from SSM, updates `.env.aws`, rerenders, restarts backend-aws, verifies in container.

**Full LAB loop (Notion → OpenClaw → PATCH):**  
See [LAB_NOTION_OPENCLAW_PATCH_VERIFICATION.md](LAB_NOTION_OPENCLAW_PATCH_VERIFICATION.md) for end-to-end verification commands and expected output.

After rendering runtime env and restarting backend-aws:

1. **Render:** `bash scripts/aws/render_runtime_env.sh` — check output for `NOTION_API_KEY=YES/NO` and `NOTION_TASK_DB=YES/NO`.
2. **Restart:** `docker compose --profile aws up -d backend-aws` (or your deploy path).
3. **Presence (no secret printed):**
   - `docker compose --profile aws exec backend-aws sh -c 'if [ -n "$NOTION_API_KEY" ]; then echo NOTION_API_KEY=present; else echo NOTION_API_KEY=not present; fi'`
   - `docker compose --profile aws exec backend-aws sh -c 'if [ -n "$NOTION_TASK_DB" ]; then echo NOTION_TASK_DB=present; else echo NOTION_TASK_DB=not present; fi'`
4. **Value of NOTION_TASK_DB only (safe to print):**  
   `docker compose --profile aws exec backend-aws printenv NOTION_TASK_DB`  
   (Do not print NOTION_API_KEY.)

## Other secrets (not in runtime.env)

These must **not** appear in `docker-compose.yml` environment blocks. They are provided only via **env_file** (e.g. `.env`, `.env.aws`):

- DATABASE_URL
- POSTGRES_PASSWORD
- CRYPTO_PROXY_TOKEN
- TELEGRAM_BOT_TOKEN_LOCAL, TELEGRAM_CHAT_ID_LOCAL (local dev)
- GF_SECURITY_ADMIN_PASSWORD (Grafana; set in `.env.aws` as `GF_SECURITY_ADMIN_PASSWORD`)

Ensure `.env` / `.env.aws` exist and contain the required keys for the profile you use. Never commit these files or example secret values.

## Never run raw `docker compose config` on EC2

Running `docker compose config` (or `docker compose --profile aws config`) prints the fully resolved configuration, including all environment variable values. That will expose secrets in logs, CI, or terminal history.

**Always use instead:**

- `scripts/aws/safe_compose_check.sh` — validates compose; does not print config.
- `scripts/aws/safe_compose_render_no_secrets.sh` — outputs redacted config for layout debugging only.

Do not run raw `docker compose config` on EC2 or in any script that could log output.

## How to verify “set” vs “not set” safely

- **Never** run `docker compose config` without redaction; it prints resolved env values. **Never run raw `docker compose config` on EC2** — it will expose secrets in logs.
- **Do** run:
  - `bash scripts/aws/safe_compose_check.sh` — validates compose (no output of config).
  - `bash scripts/aws/check_no_inline_secrets_in_compose.sh` — fails if any secret key is assigned an inline value in any compose file (references like `${VAR}` are allowed). Scans `docker-compose.yml`, `docker-compose.*.yml`, and `compose*.yml` in repo root.
- **Presence only:** After render, scripts may print `runtime.env presence=YES` and key **names** (e.g. `keys=TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID ...`). Never print values.
- **Redacted config:** For debugging layout only, use `bash scripts/aws/safe_compose_render_no_secrets.sh` — outputs config with secret values replaced by `REDACTED`.

## Inline-secrets checker: scope and tests

- **Scope:** By default the checker scans all relevant compose files in repo root: `docker-compose.yml`, `docker-compose.*.yml`, `compose*.yml`. Override with `CHECK_COMPOSE_FILE=/path/to/file` to scan a single file (e.g. for tests).
- **Reminder:** Never run raw `docker compose config` on EC2 or in CI; it prints resolved env values.
- **Run tests locally:** From repo root, run:
  - `bash tests/security/test_inline_secrets_checker.sh` — regression tests (PASS/FAIL labels only).
  - `bash scripts/aws/check_no_inline_secrets_in_compose.sh` — full scan of repo compose files.

## EC2 deploy order

1. `cd /home/ubuntu/automated-trading-platform` (or your repo path)
2. `bash scripts/aws/render_runtime_env.sh`
3. `test -f secrets/runtime.env || exit 1`
4. `bash scripts/aws/check_no_inline_secrets_in_compose.sh`
5. `bash scripts/aws/verify_no_public_ports.sh` (if present)
6. `bash scripts/aws/safe_compose_check.sh`
7. `docker compose --profile aws up -d ...` (or use `scripts/deploy_aws.sh`)

## Rollback

Restore the previous `docker-compose.yml` (and any changed scripts), then redeploy. Secrets in `secrets/runtime.env` and `.env.aws` are unchanged.
