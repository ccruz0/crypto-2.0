# 🚀 Run Authentication Diagnostic on AWS

## Execution context: Local vs AWS

Private Crypto.com API calls (user-balance, open-orders, create-order, etc.) are **AWS-only by design**. Local runs must not hit private endpoints and must not require IP allowlisting.

| Context | EXECUTION_CONTEXT | Behaviour |
|--------|--------------------|-----------|
| **Local** | `LOCAL` (default) | Public endpoints only (e.g. `get-tickers`). Private auth is **skipped**; no nonce/sig built, no HTTP to `/private/*`. Scripts exit with: *"LOCAL mode: private Crypto.com endpoints are AWS-only"*. |
| **AWS** | `AWS` | Full auth: public + private. Set `EXECUTION_CONTEXT=AWS` on AWS and allowlist the AWS egress IP in Crypto.com Exchange. |

- **Local:** `export EXECUTION_CONTEXT=LOCAL` (or leave unset); `make local-verify-auth-simple` → public get-tickers succeeds, skip message, exit 0.
- **AWS:** `export EXECUTION_CONTEXT=AWS` (e.g. in `.env.aws` or `secrets/runtime.env`); run the AWS auth verification script → public and private succeed (no 40101 if IP is allowlisted).

## Verification (build and run)

On the AWS host (e.g. `/home/ubuntu/automated-trading-platform`), use these commands to verify the diagnostic script and backend-aws image:

```bash
# From repo root on host: compile-check the script (no IndentationError)
python3 -m py_compile backend/scripts/diagnose_auth_issue.py

# Build the AWS backend image (includes scripts via Dockerfile.aws)
docker compose --profile aws build backend-aws

# Start (or restart) the backend-aws container
docker compose --profile aws up -d backend-aws

# Run the diagnostic inside the container (script path in container: /app/scripts/)
docker compose --profile aws exec backend-aws python scripts/diagnose_auth_issue.py
```

The container has `/app/scripts/diagnose_auth_issue.py` because `backend/Dockerfile.aws` copies `backend/scripts/` to `/app/scripts/` and runs a build-time `py_compile` on this script.

## Credential verification

Confirm that the Crypto.com Exchange API key/secret used on AWS is the correct pair and that the running backend container is actually using them.

### How to run

**On AWS host (inside backend-aws container):**

```bash
cd /home/ubuntu/automated-trading-platform
make aws-verify-exchange-creds
```

Or explicitly:

```bash
docker compose --profile aws exec backend-aws python /app/scripts/verify_exchange_creds_runtime.py
```

**Locally (no Docker, for comparison with AWS fingerprint):**

```bash
cd /path/to/automated-trading-platform
# Load your local .env / .env.local so EXCHANGE_CUSTOM_* are set
make verify-exchange-creds-local
```

Or:

```bash
cd backend && PYTHONPATH=. python3 scripts/verify_exchange_creds_runtime.py
```

### What the script does

- Prints a **safe fingerprint** of credentials loaded at runtime: `key_len`, `key_prefix(4)`, `key_suffix(4)`, `secret_len`, `secret_prefix(4)`, `secret_suffix(4)` (never the full key/secret).
- Shows **source** (env vars), **hostname**, **UTC time**, **outbound IP**, **LIVE_TRADING**, **USE_CRYPTO_PROXY**.
- Runs **verification**: public get-tickers, private user-balance, private get-open-orders (trade-permission check, no order placed), with up to 3 retries and small jitter. When `EXECUTION_CONTEXT=LOCAL`, only public get-tickers runs; private steps are skipped.
- Prints **PASS** if all checks succeed, **FAIL** otherwise.

### Checklist: compare AWS vs local fingerprints

| Item | AWS (container) | Local (your Mac) |
|------|-----------------|------------------|
| `key_len` | _same as Crypto.com UI?_ | _same as AWS?_ |
| `key_prefix(4)` | _match?_ | _match?_ |
| `key_suffix(4)` | _match?_ | _match?_ |
| `secret_len` | _same?_ | _same?_ |
| `outbound_ip` | _whitelisted in Exchange?_ | _different from AWS_ |
| `source` | env vars | env vars |

If AWS and local **key_prefix/key_suffix** match but AWS returns 200 and local returns 40101, the difference is usually **IP whitelist** (local IP not whitelisted) or **egress path** (local goes through different IP). If **key_prefix/key_suffix** differ, the container is using a **different credential pair** than local (e.g. different env file or runtime injection).

### Proving AWS vs local use the same key/secret

Use the **fingerprint** and **simple auth** scripts to compare credentials and behaviour.

1. **Run fingerprint on AWS** (inside backend-aws container):

   ```bash
   cd /home/ubuntu/automated-trading-platform
   make aws-fingerprint-creds
   ```

   Note: `key_len`, `key_prefix(4)`, `key_suffix(4)`, `sha256(key)[:10]`, and the same for secret, plus `env_vars_set`.

2. **Run fingerprint locally** (Mac, with your local env / Keychain-loaded vars):

   ```bash
   cd /path/to/automated-trading-platform
   make local-fingerprint-creds
   ```

3. **Compare outputs.** If they match (same lengths, same prefix/suffix, same sha256[:10]), the same key/secret pair is in use. If they differ (e.g. AWS key_len=22 vs local key_len=18), **the local key is a different value** — often because the local key comes from a different source (e.g. Keychain or a different `.env`).

4. **If mismatch: fix local key source.**  
   - If you use **Keychain** (or similar) to inject `EXCHANGE_CUSTOM_API_KEY` into the shell, ensure it returns the **same** key as on AWS (the one shown in Crypto.com UI for the AWS key).  
   - Alternatively, set `EXCHANGE_CUSTOM_API_KEY` and `EXCHANGE_CUSTOM_API_SECRET` explicitly in `.env.local` (or source a file that matches AWS `.env.aws` / runtime.env) and rerun `make local-fingerprint-creds` until the fingerprint matches AWS.

5. **Optional: run simple auth** on both sides to confirm behaviour:

   ```bash
   make aws-verify-auth-simple   # on AWS host
   make local-verify-auth-simple # on Mac (after fixing local key if needed)
   ```

**Most likely root cause when AWS works and local returns 40101:** the **local key is a different key** (e.g. Keychain or another env source returning an old/different API key). Fix by making the local environment supply the same key/secret pair as AWS (same fingerprint), then rerun fingerprint and simple auth.

### Git safety: fingerprint and auth verification

- **On AWS host:** `make aws-fingerprint-creds` and `make aws-verify-auth-simple` (run inside backend-aws container).
- **Locally:** `make local-fingerprint-creds` and `make local-verify-auth-simple` (with local env / PYTHONPATH=backend).
- **Compare:** Run fingerprint on AWS and locally; compare `key_len`, `key_prefix(4)`, `key_suffix(4)`, `sha256(key)[:10]` (and same for secret). If they match, the same key/secret pair is in use.
- **Never paste full keys into the repo.** Use `secrets/runtime.env` (git-ignored) or env injection for real credentials; keep `.env.example` and `.env.local.example` with placeholders like `YOUR_KEY_HERE`. If Git or a hook blocks with *"secret-looking KEY=VALUE line is staged"*, unstage and redact any real keys from tracked files (use only `secrets/runtime.env` or `.env.local`, which are ignored).

### If Makefile is missing or broken on EC2

Run the standalone script (no Makefile required):

```bash
cd /home/ubuntu/automated-trading-platform && bash scripts/aws/run_auth_verification_in_container.sh
```

The script builds and starts backend-aws, lists `/app/scripts`, then runs `fingerprint_creds.py` and `verify_crypto_auth_simple.py` inside the container. If either script is missing in the image, it exits non-zero with: *"Scripts missing in image: you are on a branch/commit without the scripts OR you didn't rebuild backend-aws with the right build context."*

### EC2 recovery: diagnosis and fix (dirty tree, permissions, checkout blocked)

When `git checkout` or `git pull` fails on EC2 due to local changes, untracked files, or permission errors, use these steps.

**Inspect ownership:**

```bash
cd /home/ubuntu/automated-trading-platform
ls -la .git scripts/aws || true
```

**Fix ownership** (so the ubuntu user can modify files):

```bash
sudo chown -R ubuntu:ubuntu .git scripts/aws || true
```

**If `scripts/aws` is untracked and blocks checkout** (untracked files would be overwritten):

```bash
mv scripts/aws /tmp/aws_scripts_backup_$(date +%s) || true
```

**If you must discard local changes:**

```bash
git reset --hard
git clean -fd
```

**Then:**

```bash
git checkout main
git pull --ff-only
```

**Risk:** `git reset --hard` and `git clean -fd` will delete local changes and untracked files. Use only when you do not need to keep them. After recovery, run `bash scripts/aws/run_auth_verification_in_container.sh` to rebuild and verify.

## Quick Fix Commands

Run these commands on your AWS server to diagnose and fix the authentication issue:

### Option 1: Run Individual Scripts

```bash
# SSH into AWS
ssh hilovivo-aws

# Get current IP (needs to be whitelisted)
cd ~/automated-trading-platform
docker compose --profile aws exec backend-aws python scripts/get_aws_ip.py

# Check configuration
docker compose --profile aws exec backend-aws python scripts/check_crypto_config.py

# Run full diagnostic
docker compose --profile aws exec backend-aws python scripts/diagnose_auth_issue.py

# Test connection
docker compose --profile aws exec backend-aws python scripts/test_crypto_connection.py
```

### Option 2: Run All at Once

```bash
# From your local machine, run:
ssh hilovivo-aws "cd ~/automated-trading-platform && bash backend/scripts/fix_auth_on_aws.sh"
```

## Most Common Fix

Based on the error message, the most likely issue is:

### 1. Get Your AWS IP
```bash
docker compose --profile aws exec backend-aws python scripts/get_aws_ip.py
```

### 2. Whitelist the IP
1. Go to https://exchange.crypto.com/ → Settings → API Keys
2. Edit your API key
3. Add the IP from step 1 to the whitelist
4. Save and wait 30 seconds

### 3. Verify API Key Permissions
- ✅ **Read** must be enabled
- ✅ **Trade** must be enabled (for automatic orders)

### 4. Restart Backend
```bash
docker compose --profile aws restart backend-aws
```

### 5. Test Again
```bash
docker compose --profile aws exec backend-aws python scripts/diagnose_auth_issue.py
```

## Check Current Configuration

```bash
# Check environment variables
docker compose --profile aws exec backend-aws env | grep EXCHANGE_CUSTOM

# Check if credentials are loaded
docker compose --profile aws exec backend-aws python -c "
from app.services.brokers.crypto_com_trade import CryptoComTradeClient
client = CryptoComTradeClient()
print(f'API Key configured: {bool(client.api_key)}')
print(f'API Secret configured: {bool(client.api_secret)}')
print(f'Using proxy: {client.use_proxy}')
print(f'Base URL: {client.base_url}')
"
```

## Monitor Logs

```bash
# Watch for authentication errors
docker compose --profile aws logs -f backend-aws | grep -i "authentication\|401\|auth"

# Watch all backend logs
docker compose --profile aws logs -f backend-aws
```

## Full Troubleshooting Guide

See [AUTHENTICATION_FIX_GUIDE.md](AUTHENTICATION_FIX_GUIDE.md) for detailed troubleshooting steps.

