# Quick Commands: Mac vs PROD

Comandos que funcionan desde tu **Mac** vs desde **PROD** (SSM/SSH).

---

## Desde tu Mac (ruta local)

```bash
cd ~/crypto-2.0   # En Mac: /Users/carloscruz/automated-trading-platform
```

**No uses** `/home/ubuntu/...` en Mac — esa ruta es de Linux (PROD).

---

## Deploy a PROD (desde Mac)

```bash
cd ~/crypto-2.0
./deploy_via_ssm.sh fast    # Rápido (~2 min): git pull + restart backend
./deploy_via_ssm.sh full    # Completo (~5 min): rebuild imagen + restart
```

---

## Fix Telegram Anomalies (desde Mac)

```bash
cd ~/crypto-2.0
./scripts/fix_telegram_anomalies_via_ssm.sh
```

**No ejecutes** `./scripts/fix_telegram_anomalies.sh` en Mac — falla porque usa SQLite local (sin watchlist_items). Ese script está pensado para el servidor.

---

## Entrar a PROD por SSM (desde Mac)

```bash
aws ssm start-session --target i-087953603011543c5 --region ap-southeast-1
```

Dentro de la sesión PROD:

```bash
cd /home/ubuntu/crypto-2.0 2>/dev/null || cd /home/ubuntu/crypto-2.0
git pull origin main
./scripts/fix_telegram_anomalies.sh
docker compose --profile aws ps
exit
```

---

## Cursor Bridge (desde Mac, con venv)

```bash
cd ~/crypto-2.0/backend
source .venv/bin/activate
pip install httpx   # si falta
ATP_WORKSPACE_ROOT="$(cd .. && pwd)" python -c "
from app.services.cursor_execution_bridge import run_bridge_phase2
r = run_bridge_phase2(task_id='TU_TASK_ID', ingest=True, create_pr=False)
print(r)
"
```

---

## run-atp-command (502 Bad Gateway)

Si `POST /api/agent/run-atp-command` devuelve 502:

1. Comprobar que el backend está up: `curl -s https://dashboard.hilovivo.com/api/health`
2. Reiniciar nginx en PROD: `sudo systemctl restart nginx`
3. Ver [docs/runbooks/TELEGRAM_ALERTS_NOT_SENT.md](TELEGRAM_ALERTS_NOT_SENT.md)
