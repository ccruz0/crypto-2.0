# Operations Guide

This document provides operational instructions for running the automated trading platform locally and in production.

## Always run from repo root (AWS)

If you run `docker compose` or `git` from `/home/ubuntu`, you will get:
`no configuration file provided: not found` or `fatal: not a git repository`.

Use these commands (copy/paste):

```bash
cd /home/ubuntu/automated-trading-platform
docker compose ps
docker compose logs --tail=120 backend-aws
git status -sb
```

Optional safe wrapper (works from any directory):

```bash
cd /home/ubuntu/automated-trading-platform
./dc.sh ps
./dc.sh logs --tail=120 backend-aws
```

## AWS backend deploy (one-command)

### GUARDRAIL — do not run Compose directly

- **Do not** run `docker compose --profile aws up` (or `docker compose --profile aws up -d backend-aws`) directly.
- Compose expects `secrets/runtime.env`, which exists only after the deploy script runs. Running Compose without it will fail.
- **Always** run `bash scripts/aws/aws_up_backend.sh` (or `make aws-backend-up`) instead.

### Exact commands on AWS host (Ubuntu)

**Always `cd` to repo root first:**

```bash
cd /home/ubuntu/automated-trading-platform
bash scripts/aws/aws_up_backend.sh
```

Or via Make:

```bash
cd /home/ubuntu/automated-trading-platform
make aws-backend-up
```

This will:

1. Render `secrets/runtime.env` from SSM or `.env.aws`
2. Run a smoke test (keys only, no secrets)
3. Run `docker compose --profile aws up -d --build backend-aws`
4. Wait for health, run verify, and print evidence (runtime.env presence, health)

**Lower-level deploy only (no evidence summary):**

```bash
cd /home/ubuntu/automated-trading-platform
bash scripts/aws/deploy_backend_with_secrets.sh
```

## Crypto.com SL/TP (STOP_LIMIT / TAKE_PROFIT_LIMIT) order creation

When a filled order needs protective orders, the backend creates SL/TP on Crypto.com Exchange v1.

Primary path: `private/create-order` with:

- **Stop loss**: `type=STOP_LIMIT`
- **Take profit**: `type=TAKE_PROFIT_LIMIT`

**Important (Exchange v1 change):**

- Crypto.com’s Exchange v1 docs note a migration of trigger order creation/cancellation to the **Advanced Order Management API** (effective 2025-12-17).
- To remain compatible, on failures that look like capability/API-path issues (e.g. `API_DISABLED`), the backend will also attempt the batch endpoint `private/create-order-list` (LIST) with a single order.

### What happens on failure (automatic variants fallback + evidence)

If either SL or TP creation fails, the backend automatically retries using a bounded grid of **format/key variations** (trigger key naming, numeric vs string types, `time_in_force`, optional flags, and `trigger_condition` spacing).

- **Single summary log line**: look for tag `"[SLTP_VARIANTS]"` in backend logs.
- **Evidence file (JSONL)**: written on the backend host to:
  - `/tmp/sltp_variants_<correlation_id>.jsonl`
  - Each line includes: `variant_id`, `params_keys`, `http_status`, `code`, `message`, `elapsed_ms`, `created_order_id` (if any)

### How to find `correlation_id` in logs

Search for the tag and symbol:

```bash
grep "\[SLTP_VARIANTS\]" -n backend.log | grep "symbol=ETH_USD"
```

The log line includes `correlation_id=...` and `jsonl_path=/tmp/sltp_variants_<correlation_id>.jsonl`.

### Meaning of common errors

- **140001 `API_DISABLED`**:
  - Often means **trigger/conditional order placement is disabled for that API path** (account capability or post-migration endpoint requirement), not formatting.
  - The backend will try a second path (`private/create-order-list`) once.
  - If both fail with `API_DISABLED`, it will mark conditional orders as unavailable in-memory and **stop retrying variants** until the next periodic health check (24h cache).
- **308 `Invalid price format`**:
  - Usually fixed by sending prices as **plain decimal strings** (no scientific notation) and/or using the correct trigger key (`trigger_price` vs `stop_price` vs `triggerPrice`) and correct `trigger_condition` formatting (`">= <val>"` vs `">=<val>"`).

### How we discovered the working format

- The production fallback records every rejected variant (exchange `code`/`message`) into the JSONL evidence file above.
- For deeper engineering investigations, use the **experimental trigger probe** below, which brute-forces a wider matrix and writes a separate JSONL evidence file.

### Baseline “direct on Crypto.com” payload shape (what we aim to send)

These are the baseline `params` keys we aim to use. The exchange can be strict about **key names** and **decimal formatting**, so the production fallback may vary these on failure.

**STOP_LIMIT (Stop Loss) via `private/create-order`**

- **Intent**: when market moves against the position, trigger and place a limit order to close.
- **Typical params**:

```json
{
  "instrument_name": "ETH_USD",
  "side": "SELL",
  "type": "STOP_LIMIT",
  "price": "2659.374",
  "ref_price": "2659.374",
  "quantity": "0.0033",
  "trigger_condition": "<= 2659.374",
  "time_in_force": "GOOD_TILL_CANCEL",
  "client_oid": "<uuid>"
}
```

**TAKE_PROFIT_LIMIT (Take Profit) via `private/create-order`**

- **Intent**: when market reaches profit target, trigger and place a limit order to close.
- **Typical params**:

```json
{
  "instrument_name": "ETH_USD",
  "side": "SELL",
  "type": "TAKE_PROFIT_LIMIT",
  "price": "2984.4086",
  "ref_price": "2984.4086",
  "quantity": "0.0033",
  "trigger_condition": ">= 2984.4086",
  "time_in_force": "GOOD_TILL_CANCEL",
  "client_oid": "<uuid>"
}
```

**Batch fallback via `private/create-order-list` (LIST)**

When the API indicates the trigger-order path is disabled, the backend can fall back to `private/create-order-list` with `contingency_type=LIST` and an `order_list` containing one order. In this path, the trigger price field is `trigger_price`:

```json
{
  "contingency_type": "LIST",
  "order_list": [
    {
      "instrument_name": "ETH_USD",
      "side": "SELL",
      "type": "STOP_LIMIT",
      "price": "2659.374",
      "quantity": "0.0033",
      "trigger_price": "2659.374",
      "time_in_force": "GOOD_TILL_CANCEL",
      "client_oid": "<uuid>"
    }
  ]
}
```

**Notes**

- Prices/quantities should be **plain decimal strings** (avoid scientific notation).
- `trigger_condition` spacing can matter (some endpoints accept `">= 123.45"` but reject `">=123.45"` and vice versa), which is why the fallback tries both.

## Crypto.com SL/TP trigger probe (experimental)

Use this when conditional orders (`STOP_LIMIT` / `TAKE_PROFIT_LIMIT`) fail but MARKET/LIMIT works, and you need **evidence**.

**Safety defaults:**

- Hard cap enforced: `CRYPTO_PROBE_MAX_NOTIONAL_USD` (default: `1.0`)
- Attempts to cancel any created probe orders when `dry_run=true` (endpoint forces this)

**Enable (guarded):**

```bash
export ENABLE_CRYPTO_PROBE=true
export CRYPTO_PROBE_MAX_NOTIONAL_USD=1.0
```

**Run (local):**

```bash
curl -X POST http://127.0.0.1:8002/api/control/crypto/trigger-probe \
  -H 'Content-Type: application/json' \
  -d '{"instrument_name":"ETH_USD","side":"SELL","qty":"0.0001","ref_price":2500,"max_variants":120}'
```

**Output:**

- The response returns `correlation_id` and `jsonl_path`
- The JSONL file is written on the backend host at `/tmp/trigger_probe_<correlation_id>.jsonl`
- Each line is one variant attempt with redacted payload + full response JSON

## Arranque local con secrets

### 1. Configurar secrets de Postgres

```bash
cd /Users/carloscruz/automated-trading-platform

mkdir -p secrets

printf "CHANGE_ME_STRONG_PASSWORD_64" > secrets/pg_password

chmod 600 secrets/pg_password
```

**⚠️ IMPORTANTE**: Reemplaza `CHANGE_ME_STRONG_PASSWORD_64` con una contraseña segura antes de usar en producción.

### 2. Iniciar servicios

```bash
cd /Users/carloscruz/automated-trading-platform

docker compose up -d --build
```

### 3. Verificar estado de servicios

```bash
cd /Users/carloscruz/automated-trading-platform

docker compose ps
```

### 4. Ver logs de base de datos

```bash
cd /Users/carloscruz/automated-trading-platform

docker compose logs -f db
```

## Configuración de Secrets

Los secrets de Postgres se gestionan mediante Docker Compose secrets:

- **Ubicación**: `./secrets/pg_password`
- **Permisos**: `600` (solo lectura para el propietario)
- **No se incluye en git**: El directorio `secrets/` está en `.gitignore`

### Estructura de secrets

```
secrets/
  └── pg_password          # Contraseña de PostgreSQL (NO commitear)
```

## Variables de Entorno

Las contraseñas se gestionan mediante secrets en lugar de variables de entorno para mayor seguridad:

- `POSTGRES_PASSWORD_FILE`: Apunta a `/run/secrets/pg_password` dentro del contenedor
- `POSTGRES_INITDB_ARGS`: Configura autenticación scram-sha-256

## Verificación de Seguridad

### Healthchecks

Todos los servicios incluyen healthchecks configurados:

- **Frontend**: Verifica que el servidor responda en `http://localhost:3000/`
- **Backend**: Verifica que el servidor escuche en el puerto 8002
- **Database**: Verifica que PostgreSQL esté listo con `pg_isready`

### Configuración de Seguridad

Los servicios están configurados con:

- `security_opt: no-new-privileges:true`: Previene escalada de privilegios
- `cap_drop: ALL`: Elimina todas las capacidades del kernel
- `read_only: true`: Sistema de archivos de solo lectura (excepto tmpfs)
- `tmpfs: /tmp`: Montaje temporal para directorios de escritura
- **Límites de recursos**: CPU y memoria limitadas por servicio

## Troubleshooting

### El contenedor no inicia

1. Verifica que el secret existe:
   ```bash
   ls -la secrets/pg_password
   ```

2. Verifica los permisos:
   ```bash
   chmod 600 secrets/pg_password
   ```

3. Verifica los logs:
   ```bash
   docker compose logs db
   ```

### Problemas de conectividad

1. Verifica que los servicios estén healthy:
   ```bash
   docker compose ps
   ```

2. Verifica la salud de cada servicio:
   ```bash
   docker inspect <container_name> | grep -A 10 Health
   ```

## Producción

Para producción:

1. **Genera una contraseña segura**:
   ```bash
   openssl rand -base64 32 > secrets/pg_password
   chmod 600 secrets/pg_password
   ```

2. **Usa secrets management**:
   - Docker Swarm secrets
   - Kubernetes secrets
   - AWS Secrets Manager
   - HashiCorp Vault

3. **Rotación de secrets**:
   - Cambia la contraseña regularmente
   - Actualiza `secrets/pg_password`
   - Reinicia los servicios: `docker compose restart db`

## Fix Telegram/Alerts not sending in AWS

Use the one-command AWS path (**always `cd` first**):

```bash
cd /home/ubuntu/automated-trading-platform
bash scripts/aws/aws_up_backend.sh
```

What it does:

- Renders `secrets/runtime.env` from SSM (preferred) or `.env.aws` fallback
- Ensures `secrets/runtime.env` exists before compose (compose never fails for missing file when using the script)
- Builds and starts `backend-aws`, waits for `http://localhost:8002/health`
- Verifies admin endpoint, Telegram logs, and DB rows for SENT/BLOCKED with `reason_code`
- Prints evidence (runtime.env presence, health) without exposing secrets

## Production E2E Verification

Verify the complete pipeline: Signal → Alert → Telegram → Trade Decision → Order → TP/SL

### Quick Start (DRY_RUN mode - safe, no real orders)

```bash
cd /Users/carloscruz/automated-trading-platform
make prod-e2e
```

Or directly:

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/verify_alerts_and_trading_e2e.sh --dry-run --symbol BTC_USDT
```

### What PASS Looks Like

A successful verification report shows:

- ✅ Backend health endpoint accessible
- ✅ Evaluation triggered successfully
- ✅ Telegram message found in database (not blocked)
- ✅ Telegram send confirmed in logs (HTTP 200)
- ✅ Order creation verified (or skip reason documented)
- ✅ TP/SL orders found with values matching strategy configuration

### Report Location

The verification report is saved to:

```
docs/PRODUCTION_E2E_VERIFICATION_REPORT.md
```

The report includes:
- Timestamps for each stage
- Correlation ID for tracing
- Database query results
- Log evidence
- TP/SL values and strategy comparison
- Commands executed

### REAL Mode (Actual Orders)

⚠️ **WARNING**: REAL mode places actual orders on Crypto.com exchange.

```bash
cd /Users/carloscruz/automated-trading-platform
make prod-e2e-real SYMBOL=BTC_USDT
```

Or directly:

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/verify_alerts_and_trading_e2e.sh --real --symbol BTC_USDT
```

### What Gets Verified

1. **Backend Health**: Confirms backend is reachable and responding
2. **Signal Evaluation**: Triggers a real evaluation for the test symbol
3. **Telegram Delivery**: 
   - Verifies message was sent (HTTP 200 from Telegram API)
   - Confirms message appears in database
   - Checks logs for send confirmation
4. **Trade Decision**:
   - Verifies order creation when Trade=YES
   - Documents skip reasons when orders are blocked
   - Confirms trade_enabled gating works
5. **Order Placement** (REAL mode only):
   - Confirms order exists on Crypto.com exchange
   - Verifies order details match database
6. **TP/SL Placement**:
   - Verifies TP/SL orders are created
   - Confirms values come from strategy configuration (not fixed percentages)
   - Shows calculated TP/SL values for the test symbol

### Troubleshooting

#### Health Check Returns HTTP 000000

If the health check shows "HTTP 000000", this means:

1. **All external URL probes failed** - The backend may not be accessible from your Mac
2. **SSM fallback will be used** - The script automatically falls back to checking health via SSM
3. **This is acceptable** - As long as SSM health check succeeds (HTTP 200), verification can continue

**What to check:**
- Security group rules (port 8002 may not be open to your IP)
- Backend container status: `docker compose --profile aws ps backend-aws`
- Backend logs: `docker compose --profile aws logs backend-aws --tail=50`

**Expected behavior:**
- External probes fail → SSM fallback succeeds → Verification continues ✅
- All probes fail (including SSM) → Verification stops ❌

#### Other Common Issues

1. **Telegram message not found:**
   - Check correlation_id matches in logs: `grep "e2e-YYYYMMDD" backend logs`
   - Verify symbol has `alert_enabled=true` in database
   - Check if message was blocked (see `blocked=true` in query results)

2. **Order not created (REAL mode):**
   - Check `trade_enabled=true` for the symbol
   - Review skip reasons in report (order_skipped, decision_type, reason_code)
   - Verify position limits and cooldowns

3. **TP/SL values don't match:**
   - Check strategy configuration for the symbol
   - Verify ATR data is available (required for ATR-based calculations)
   - Review calculation output in report

4. **Backend not reachable:**
   - Verify backend container is running: `docker compose --profile aws ps`
   - Check health via SSM: The script will automatically use SSM if external probes fail
   - Review container logs for errors

**Quick Diagnostics:**

```bash
cd /Users/carloscruz/automated-trading-platform

# Check backend status via SSM
aws ssm send-command \
  --instance-ids i-08726dc37133b2454 \
  --region ap-southeast-1 \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["cd /home/ubuntu/automated-trading-platform","docker compose --profile aws ps backend-aws","docker compose --profile aws logs --tail=20 backend-aws"]' \
  --query 'Command.CommandId' --output text
```

