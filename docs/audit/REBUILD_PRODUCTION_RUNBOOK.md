# Rebuild producción – Runbook de ejecución

**Dinero real = rebuild obligatorio.** Solo ejecución. Sin teoría.

---

## FASE 0 — Congelar entorno actual (~10 min)

**No borrar aún.**

### 1. Dump final de la base de datos

```bash
docker exec -t postgres_hardened pg_dump -U trader -d atp > atp_backup_$(date +%F).sql
```

Verificar:

```bash
ls -lh atp_backup_*.sql
```

Descargar el archivo a tu máquina local (scp/rsync).

---

### 2. Evidencias (opcional)

Carpeta `incident_2026-02-20` (o la que tengas). Descargarla completa.

---

### 3. Listar imágenes

```bash
docker images > images_before_rebuild.txt
```

Guardar también.

---

Cuando tengas el dump y los archivos descargados, paramos todo.

---

## FASE 1 — Terminar instancia

En AWS:

1. Detach Elastic IP (si aplica).
2. Terminate instance.
3. No reutilizar esa máquina.

No usar snapshots para volver a producción. Solo para forense si quieres.

**Confirma cuando esté terminada.**

---

## FASE 2 — Nueva instancia limpia

1. **Nueva EC2**
   - AMI oficial Ubuntu LTS.
   - Sin snapshot viejo.
   - Nuevo security group.

2. **Security group mínimo**

   **Inbound:**
   - 22 → solo tu IP.
   - 80/443 si hace falta.
   - Nada más.

   **Outbound:** idealmente restringido; si no puedes aún, se refina después.

---

## Troubleshooting: SSH timeout (nc -vz … 22)

Si `nc -vz <IP> 22` hace timeout, el problema es red / Security Group, no Docker.

**1) IP correcta**  
EC2 → Instances → selecciona la **nueva** instancia. Anota:
- Public IPv4 address
- Public IPv4 DNS  
No uses la IP de la instancia antigua si no has reasignado el Elastic IP.

**2) Security Group**  
Inbound debe tener:
- Type: SSH, Port: 22, Source: **tu IP actual** (ej. `x.x.x.x/32`).  
Tu IP: `curl ifconfig.me` (o https://ifconfig.me). Añade esa IP/32 en la regla SSH.

**3) IP pública en la instancia**  
En detalles de la instancia:
- Auto-assign public IP → debe estar **Enabled**.  
Si no tiene IP pública: asigna Elastic IP o habilita auto-assign y recrea.

**4) Test desde tu Mac** (después de ajustar SG):
```bash
nc -vz <NEW_PUBLIC_IP> 22
# Esperado: Connection to <ip> port 22 [tcp/ssh] succeeded!

ssh -i <tu-key>.pem ubuntu@<NEW_PUBLIC_IP>
```

**Importante:** `cd /home/ubuntu/automated-trading-platform` solo existe **dentro** de la EC2. Ese comando debe ejecutarse **después** de hacer `ssh ubuntu@<IP>`, no en tu Mac.

**Para diagnosticar, responde con:**
1. ¿La instancia nueva tiene Public IPv4?
2. ¿Tiene Elastic IP asociada?
3. ¿Qué IP estás usando en `nc` / `ssh`?
4. Inbound rule SSH del Security Group (Type, Port, Source).

---

## FASE 3 — Instalación limpia

SSH a la nueva máquina:

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker ubuntu
newgrp docker
```

Verificar:

```bash
docker --version
docker compose version
```

---

## FASE 4 — Deploy limpio desde git

```bash
git clone <your_repo_url>
cd automated-trading-platform
git checkout main
```

**Antes de levantar nada – verificación crítica:**

```bash
# 1) NO debe haber volumen que monte docker.sock (sí puede haber comentarios "REMOVED")
grep -n '/var/run/docker.sock' docker-compose.yml
# Esperado: salida vacía. Si hay línea, debe ser solo un comentario (ej. "# SECURITY: ... REMOVED").
grep -E '^\s*-\s*/var/run/docker\.sock' docker-compose.yml && echo "FALLO: hay mount de docker.sock" || echo "OK: sin mount docker.sock"

# 2) Backend no root: en Dockerfile.aws debe haber USER appuser
grep -n "USER appuser" backend/Dockerfile.aws
# Esperado: 1 línea.

# 3) Restart protegido: debe existir _verify_diagnostics_auth en restart_backend
grep -n "_verify_diagnostics_auth(request)" backend/app/api/routes_monitoring.py | head -5
# Esperado: al menos una línea en restart_backend y una en run_workflow.

# 4) Frontend healthcheck sin wget: debe usar node, no wget
grep -A1 "HEALTHCHECK" frontend/Dockerfile
# Esperado: CMD con "node" y "http". No "wget".
```

Confirma manualmente estos cuatro puntos.

---

## FASE 5 — Rotación de secretos (CRÍTICO)

**Antes de levantar servicios:**

1. **Crypto.com:** generar nuevas API keys y revocar las antiguas.
2. **Telegram:** regenerar bot token (BotFather).
3. **Base de datos:** nueva contraseña para el usuario de la app.
4. **OpenAI / otros:** nuevas keys si se usan.

Crear/actualizar en la nueva instancia:

- `.env`, `.env.aws`, `secrets/runtime.env` (o los que uses) con los valores nuevos.
- No reutilizar ningún secreto de la instancia comprometida.

---

## FASE 6 — Levantar stack limpio

```bash
cd automated-trading-platform
docker compose --profile aws up -d --build
```

Verificar:

```bash
docker ps
```

---

## FASE 7 — Restaurar base de datos

Sustituir `YYYY-MM-DD` por la fecha del dump:

```bash
cat atp_backup_YYYY-MM-DD.sql | docker exec -i postgres_hardened psql -U trader -d atp
```

Verificar tablas:

```bash
docker exec -it postgres_hardened psql -U trader -d atp -c "\dt"
```

---

## FASE 8 — Hardening adicional en compose

En este repo ya están aplicados para `backend-aws`:

- `security_opt: no-new-privileges:true`
- `cap_drop: ALL`

Si quieres añadir **read_only** en más servicios:

- **frontend-aws:** ya tiene `read_only: true` y `tmpfs: /tmp`.
- **backend-aws:** si añades `read_only: true`, asegura tmpfs para directorios de escritura (p. ej. `/tmp`, `/app/backend/ai_runs` si aplica). Revisar que el volumen de datos (`/data`) siga montado para trading config.

Revisar `docker-compose.yml` y aplicar solo lo que no rompa el arranque.

---

## FASE 9 — Egress mínimo (host)

En el host nuevo:

```bash
sudo ufw default deny outgoing
sudo ufw allow out 53
sudo ufw allow out 443
sudo ufw allow out 80
sudo ufw allow out 123/udp
sudo ufw enable
```

Ajustar después si necesitas más puertos (p. ej. para Telegram, Crypto.com, etc.).

---

## FASE 10 — Validación final

**No debe aparecer docker.sock en ningún contenedor:**

```bash
docker inspect $(docker ps -q) --format '{{.Name}} {{range .Mounts}}{{.Source}}:{{.Destination}} {{end}}' | grep -i docker.sock
# Esperado: salida vacía (no matches).
```

**Frontend sin wget:**

```bash
docker exec -it $(docker ps -q -f name=frontend) which wget
# Esperado: vacío o "not found".
```

**Resumen de mounts (revisar a ojo que no haya docker.sock):**

```bash
docker inspect $(docker ps -q) --format '{{.Name}} {{range .Mounts}}{{.Source}}:{{.Destination}} {{end}}'
```

---

## Después del rebuild

- Arquitectura sin docker.sock y sin vector de escalada conocido.
- Sin persistencia del atacante en la instancia nueva.
- Secretos rotados (DB, Telegram, Crypto.com, etc.).

Cuando tengas:
- Dump hecho y descargado
- Instancia antigua terminada
- Nueva instancia creada

avanzamos fase por fase sin errores.
