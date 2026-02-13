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

**Source:** AWS SSM (primary) or `.env.aws` (fallback). Do not change secret sources unless necessary.

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
