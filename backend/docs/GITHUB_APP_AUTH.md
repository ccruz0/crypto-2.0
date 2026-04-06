# GitHub App authentication (EC2 backend)

The trading backend uses a **GitHub App** installation to call the GitHub API (workflow dispatch, Cursor bridge flows, deploy triggers). On AWS, when **`ATP_TRADING_ONLY` is not `1`**, startup requires either:

1. **GitHub App** — three environment variables (preferred), or  
2. **Emergency legacy** — `ALLOW_LEGACY_GITHUB_PAT=true` plus `GITHUB_TOKEN` (personal access token), documented only for rollback.

Do **not** commit real values. Never paste secrets into logs or chat.

## Required environment variables (GitHub App)

| Variable | Description |
|----------|-------------|
| `GITHUB_APP_ID` | Numeric App ID from GitHub → Settings → Developer settings → GitHub Apps → your app. |
| `GITHUB_APP_INSTALLATION_ID` | Installation ID for the org/repo (GitHub App → Install app, or API). |
| `GITHUB_APP_PRIVATE_KEY_B64` | Base64 encoding of the App’s **`.pem` private key** (single line, no PEM headers in env). |

### Encode the private key (operator machine)

Linux:

```bash
base64 -w0 < /path/to/app-private-key.pem
```

macOS:

```bash
base64 -i /path/to/app-private-key.pem | tr -d '\n'
```

Put the output on one line as the value of `GITHUB_APP_PRIVATE_KEY_B64`.

## How values reach `secrets/runtime.env`

**`scripts/aws/render_runtime_env.sh`** reads:

1. **AWS Systems Manager Parameter Store** (when `aws sts get-caller-identity` succeeds):

   **Production path**

   - `/automated-trading-platform/prod/github_app/app_id`
   - `/automated-trading-platform/prod/github_app/installation_id`
   - `/automated-trading-platform/prod/github_app/private_key_b64` (SecureString recommended)

   **LAB path** (used when a prod value is empty)

   - `/automated-trading-platform/lab/github_app/app_id`
   - `/automated-trading-platform/lab/github_app/installation_id`
   - `/automated-trading-platform/lab/github_app/private_key_b64`

2. **`.env.aws`** in the repo root (fallback mode, or override when SSM “primary” telegram keys are used — see script comments). Set the same three variable names there if not using SSM.

3. When `source=primary`, **`.env.aws` can override** SSM for GitHub App keys if the lines are present (operator/LAB override).

The script appends `GITHUB_APP_*` to **`secrets/runtime.env`** only for non-empty values. The render summary prints `GITHUB_APP=YES` only when **all three** are present in memory after merges.

## Legacy PAT (`GITHUB_TOKEN`)

**`/automated-trading-platform/prod/github_token`** is still fetched and written as **`GITHUB_TOKEN`** when non-empty. On AWS, using **only** `GITHUB_TOKEN` without GitHub App is **blocked** unless **`ALLOW_LEGACY_GITHUB_PAT=true`** is set in `secrets/runtime.env` (see `backend/app/factory.py`). Prefer GitHub App for normal operation.

## Store parameters in SSM (example)

Replace `REGION` and use your account’s path names as above. **Do not** echo secret values in CI or shared terminals.

```bash
aws ssm put-parameter --region REGION --name /automated-trading-platform/prod/github_app/app_id --value "YOUR_APP_ID" --type String --overwrite
aws ssm put-parameter --region REGION --name /automated-trading-platform/prod/github_app/installation_id --value "YOUR_INSTALLATION_ID" --type String --overwrite
aws ssm put-parameter --region REGION --name /automated-trading-platform/prod/github_app/private_key_b64 --value "YOUR_BASE64_KEY" --type SecureString --overwrite
```

IAM on the instance role (or operator CLI) needs **`ssm:GetParameter`** (and `kms:Decrypt` if the key uses a CMK).

## Operator flow after merge (LAB / EC2)

From repo root (path may be `crypto-2.0` or `automated-trading-platform`):

1. **Render** `secrets/runtime.env` (pulls SSM and/or `.env.aws`):

   ```bash
   bash scripts/aws/render_runtime_env.sh
   ```

   Confirm the line includes `GITHUB_APP=YES` when all three App values are configured.

2. **Enable full automation** (Notion scheduler + GitHub checks): set **`ATP_TRADING_ONLY=0`** for `backend-aws`. In `docker-compose.yml`, `ATP_TRADING_ONLY=${ATP_TRADING_ONLY:-1}` is resolved from the **host shell** when you run Compose, and that `environment` entry overrides `env_file` for the same key — so use **`export ATP_TRADING_ONLY=0`** on the host before `docker compose`, or set `ATP_TRADING_ONLY=0` in the repo **`.env`** file used for Compose interpolation. Do not rely on `secrets/runtime.env` alone for this variable unless your compose file is changed to read it from there.

3. **Recreate backend**

   ```bash
   docker compose --profile aws up -d --force-recreate backend-aws
   ```

4. **Verify** (no secret values):

   ```bash
   docker compose --profile aws logs backend-aws --tail=80
   ```

   Expect no `RuntimeError` about GitHub App credentials; expect startup logs for Notion/GitHub auth diagnostics as in `factory.py`.

   ```bash
   ./scripts/verify_deploy_secrets.sh
   ```

## Related files

- `scripts/aws/render_runtime_env.sh` — implementation  
- `secrets/runtime.env.example` — template and comments  
- `backend/app/factory.py` — AWS startup checks for GitHub auth when not trading-only  
