# Comandos para ejecutar tú (copy-paste)

Comandos listos para copiar en tu terminal. Requieren: AWS CLI configurado con credenciales que tengan permisos sobre EC2/SSM en la región ap-southeast-1.

---

## 1. Entrar a PROD cuando SSM está Connection lost (recomendado)

SSM en atp-rebuild-2026 puede seguir en Connection lost. Para entrar igual:

1. **SG** sg-07f5b0221b7e69efe: **Edit inbound rules** → **Add rule**: Type **SSH**, Port **22**, Source **My IP** → Save.
2. **EC2** → **Instances** → **atp-rebuild-2026** → **Connect** → **EC2 Instance Connect** → **Connect** (terminal en el navegador).
3. Cuando termines, opcional: quitar la regla SSH.

---

## 2. Restaurar SSM en PROD (reboot atp-rebuild-2026)

Solo si quieres que Session Manager funcione en PROD. La instancia se reiniciará (~2–3 min de indisponibilidad).

```bash
# Región
export AWS_REGION=ap-southeast-1

# Reboot PROD
aws ec2 reboot-instances --region $AWS_REGION --instance-ids i-087953603011543c5

# Esperar 2-3 minutos, luego comprobar SSM
sleep 120
aws ssm describe-instance-information --region $AWS_REGION \
  --filters "Key=InstanceIds,Values=i-087953603011543c5" \
  --query 'InstanceInformationList[0].PingStatus' --output text
```

Si sale `Online`, SSM está bien. Si sigue `ConnectionLost`, sigue **docs/aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md** (diagnóstico).

---

## 3. Comprobar estado PROD/LAB (sin reboot)

```bash
cd /ruta/a/automated-trading-platform   # o crypto-2.0
./scripts/aws/prod_status.sh
```

O solo API:

```bash
./scripts/aws/verify_prod_public.sh
```

---

## 4. Disparar deploy a PROD (desde GitHub)

No se hace por terminal; se hace en GitHub:

1. **Opción A:** Haz **push a la rama `main`** (el workflow **Deploy to AWS EC2 (Session Manager)** se ejecuta solo; es el deploy por defecto).
2. **Opción B:** Repo → **Actions** → **Deploy to AWS EC2 (Session Manager)** → **Run workflow** → Run.

Luego en el mismo run revisa que el paso "Deploy to EC2 using Session Manager" termine en verde.

---

## 5. OpenClaw en LAB (en la instancia LAB)

Entras a la instancia LAB por **Session Manager** (EC2 → Instances → atp-lab-ssm-clean → Connect → Session Manager). Luego, en esa sesión:

```bash
# Crear directorio de secretos y token (sustituir TOKEN por tu PAT real; no dejar en historial)
mkdir -p ~/secrets
chmod 700 ~/secrets
echo -n "TU_FINE_GRAINED_PAT_AQUI" > ~/secrets/openclaw_token
chmod 600 ~/secrets/openclaw_token

# Clone del repo (si no existe)
cd ~
git clone https://github.com/ccruz0/crypto-2.0.git automated-trading-platform 2>/dev/null || (cd automated-trading-platform && git pull)

cd ~/automated-trading-platform
cp .env.lab.example .env.lab
chmod 600 .env.lab
# Editar .env.lab: GIT_REPO_URL, OPENCLAW_TOKEN_PATH=/home/ubuntu/secrets/openclaw_token
nano .env.lab

# Levantar OpenClaw
docker compose -f docker-compose.openclaw.yml up -d
docker compose -f docker-compose.openclaw.yml ps
```

Sustituye `TU_FINE_GRAINED_PAT_AQUI` por tu Personal Access Token de GitHub (fine-grained: Contents R/W, Pull requests R/W, Metadata R). No compartas ese valor. Detalle completo: **docs/openclaw/SIGUIENTE_PASOS_OPENCLAW.md** y **LAB_SETUP_AND_VALIDATION.md**.

---

## 6. Notion: hacer que el scheduler recoja una tarea (PROD)

`NOTION_API_KEY` está en **secrets/runtime.env** en el servidor. Para que una tarea **Planned** se recoja sin esperar al ciclo del scheduler:

1. Conéctate a PROD (SSM o EC2 Instance Connect).
2. Añade `NOTION_TASK_DB` si aún no está (sustituye por el ID de tu base Notion si es otra):
   ```bash
   cd /home/ubuntu/crypto-2.0
   grep -q NOTION_TASK_DB secrets/runtime.env || echo 'NOTION_TASK_DB=eb90cfa139f94724a8b476315908510a' >> secrets/runtime.env
   docker compose --profile aws restart backend-aws
   ```
3. Ejecuta un ciclo del scheduler:
   ```bash
   ./scripts/run_notion_task_pickup.sh
   ```

Detalle: [NOTION_TASK_TO_CURSOR_AND_DEPLOY.md](../runbooks/NOTION_TASK_TO_CURSOR_AND_DEPLOY.md) § Task stuck in Planned.

---

## 7. Auditoría AWS (instancias + SSM)

```bash
cd /ruta/a/automated-trading-platform
./scripts/aws/aws_audit_live.sh
```

---

**Referencias:** [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](RUNBOOK_SSM_PROD_CONNECTION_LOST.md), [POST_DEPLOY_VERIFICATION.md](POST_DEPLOY_VERIFICATION.md), [../openclaw/SIGUIENTE_PASOS_OPENCLAW.md](../openclaw/SIGUIENTE_PASOS_OPENCLAW.md), [../runbooks/NOTION_TASK_TO_CURSOR_AND_DEPLOY.md](../runbooks/NOTION_TASK_TO_CURSOR_AND_DEPLOY.md).
