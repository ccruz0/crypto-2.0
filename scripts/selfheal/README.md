# ATP Self-Heal (prod)

Scripts para verificación y auto-recuperación en EC2: disk, containers, backend health, nginx. **Sin secrets, sin endpoints protegidos.**

## Qué hace

- **verify.sh:** Comprueba disco &lt;90%, ningún container unhealthy, `/api/health` ok, y **PASS operativo**: `db_status` up, `market_data.status` PASS, `market_updater.status` PASS, `signal_monitor.status` PASS. **No exige** que telegram ni trade_system estén PASS (pueden estar deshabilitados por diseño). Sale con código 2–8 según fallo.
- **heal.sh:** Con lock, si disco ≥90% trunca logs Docker y hace prune; reinicia docker; reinicia stack con `docker compose --profile aws` **solo si existe .env** (si falta, imprime mensaje y omite compose); llama a **POST** `/api/health/fix` (sin x-api-key); recarga nginx solo si `nginx -t` pasa.
- **run.sh:** Ejecuta verify → si falla ejecuta heal → vuelve a verify. Útil para timer/cron.

## Endpoint /api/health/fix

El backend expone **POST /api/health/fix** en `routes_control.py` **sin autenticación**. Solo **reinicia** servicios internos (exchange_sync, signal_monitor, trading_scheduler). **No muta schema.** Para crear tablas (watchlist_items, etc.) usar `scripts/db/bootstrap.sh` (una vez o en deploy) o POST /api/health/repair (con x-api-key).

Comprobar en EC2:

```bash
curl -i http://127.0.0.1:8002/api/health/fix
# GET puede 405; usar:
curl -i -X POST http://127.0.0.1:8002/api/health/fix
```

Si devuelve 200, el self-heal puede “arreglar” reiniciando esos servicios. Si 404, heal.sh sigue funcionando (restarts, prune, nginx reload) pero no llama a backend.

## Instalación en EC2

**Runbook completo:** [docs/runbooks/EC2_SELFHEAL_DEPLOY.md](../../docs/runbooks/EC2_SELFHEAL_DEPLOY.md) (git pull, chmod, systemd, status, .env fallback).  
**Fix market data + verify.sh ahora:** [docs/runbooks/EC2_FIX_MARKET_DATA_NOW.md](../../docs/runbooks/EC2_FIX_MARKET_DATA_NOW.md).  
**Bootstrap DB schema (watchlist_items):** [docs/runbooks/EC2_DB_BOOTSTRAP.md](../../docs/runbooks/EC2_DB_BOOTSTRAP.md). Ejecutar **antes** de habilitar el timer si market_data/market_updater fallan por tabla faltante.  
**Restaurar verify.sh sin heredoc:** `python3 scripts/selfheal/emit_verify_sh.py` (ejecutar desde raíz del repo).

### 0) Bootstrap DB schema (antes del timer)

Si `watchlist_items` no existe, market-updater falla y health queda en FAIL. Crear schema una vez:

```bash
cd ~/automated-trading-platform
./scripts/db/bootstrap.sh
```

Ver [EC2_DB_BOOTSTRAP.md](../../docs/runbooks/EC2_DB_BOOTSTRAP.md) para comandos completos y diagnóstico.

### 1) Scripts (vía repo)

```bash
cd ~/automated-trading-platform
git pull origin main
chmod +x scripts/selfheal/verify.sh scripts/selfheal/heal.sh scripts/selfheal/run.sh
```

### 2) Systemd (timer cada 2 min)

```bash
sudo cp /home/ubuntu/automated-trading-platform/scripts/selfheal/systemd/atp-selfheal.service /etc/systemd/system/
sudo cp /home/ubuntu/automated-trading-platform/scripts/selfheal/systemd/atp-selfheal.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now atp-selfheal.timer
sudo systemctl status atp-selfheal.timer --no-pager
```

### 3) Prueba manual

```bash
cd ~/automated-trading-platform
./scripts/selfheal/verify.sh
./scripts/selfheal/run.sh
```

Logs del último run:

```bash
sudo journalctl -u atp-selfheal.service -n 80 --no-pager
```

## Recomendaciones (evitar otro disk full)

### A) Rotación de logs Docker

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
JSON
sudo systemctl restart docker
```

### B) Retención Prometheus

En `docker-compose.yml` el servicio prometheus ya incluye `--storage.tsdb.retention.time=15d`. Tras `docker compose --profile aws up -d`, el contenedor aplica la retención.

---

## Verificación en producción (5 checks)

Ejecutar en EC2 para cerrar el círculo: timer activo, lock evita bucles, verify estable ante JSON inesperado, Prometheus con retención, disco bajo control.

### 1) Timer + últimas ejecuciones

```bash
sudo systemctl status atp-selfheal.timer --no-pager
sudo systemctl list-timers | grep -i atp-selfheal || true
sudo journalctl -u atp-selfheal.service -n 120 --no-pager
```

**Qué ver:** Timer activo (`active (waiting)`); ejecuciones cada ~2 min; en logs "PASS" o "HEALED", no "STILL_FAIL" repetido. Si ves HEALED muchas veces, investigar causa raíz.

### 2) Verify manual y códigos de salida

```bash
cd ~/automated-trading-platform
./scripts/selfheal/verify.sh; echo "exit=$?"
```

**Objetivo:** Salida "PASS" y `exit=0`. Cualquier otro código (2–8) indica qué falla (DISK, CONTAINERS_UNHEALTHY, API_HEALTH, DB, MARKET_DATA, MARKET_UPDATER, SIGNAL_MONITOR). El script usa `jq -r '.campo // empty'`; si el JSON es inesperado o no JSON, los campos quedan vacíos y verify falla de forma segura (FAIL:DB o similar), no se cuelga.

### 3) Prometheus retención aplicada

```bash
docker exec atp-prometheus sh -c 'ps aux' 2>/dev/null | grep -E "prometheus|retention" | grep -v grep
```

**Debe aparecer:** `--storage.tsdb.retention.time=15d` en la línea de comando del proceso Prometheus.

### 4) Dashboard sin “stale” (health system)

```bash
curl -s http://127.0.0.1:8002/api/health/system | jq
```

**Mínimo esperado:** `db_status` "up", `market_data.status` "PASS", `market_updater.status` "PASS", `signal_monitor.status` "PASS". Con eso verify.sh debería dar PASS.

### 5) Docker log rotation (blindaje disco)

```bash
cat /etc/docker/daemon.json || true
```

Si no existe o no tiene `log-opts`, crearlo:

```bash
sudo tee /etc/docker/daemon.json >/dev/null <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
JSON
sudo systemctl restart docker
```

Luego `docker compose --profile aws up -d` para levantar de nuevo los contenedores.

---

## Regla de oro

**Si ves "HEALED" más de 3 veces al día, algo está mal:** hay que arreglar la causa raíz en lugar de depender del heal en bucle.

---

## Lock (evitar bucles simultáneos)

`heal.sh` usa `flock -n` sobre `/var/lock/atp-selfheal.lock`. Si otro self-heal está corriendo, sale en silencio (`exit 0`). El timer solo lanza un run cada 2 min y cada run es oneshot, así que no deberían solaparse; el lock protege por si se dispara manualmente mientras el timer corre.

---

## Próximos pasos (opcionales)

- Contador de fallos consecutivos en run.sh o en un wrapper.
- Alerta Telegram solo si verify falla 3 veces seguidas (evitar ruido).
- Snapshot corto en el mensaje (disk %, unhealthy count, market_updater age).

Cuando el timer y los scripts estén desplegados en EC2, usar [EC2_SELFHEAL_DEPLOY.md](../../docs/runbooks/EC2_SELFHEAL_DEPLOY.md) para comprobar estado y journal.
