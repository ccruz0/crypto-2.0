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

