# OpenClaw en LAB — Siguiente pasos

Orden mínimo para tener OpenClaw corriendo en **atp-lab-ssm-clean** (i-0d82c172235770a0d).

---

## 1. Acceso a la instancia LAB

- **SSM:** EC2 → Instances → atp-lab-ssm-clean → Connect → Session Manager (LAB tiene SSM Online).
- O SSH si tienes clave y el SG lo permite.

---

## 2. Preparar el host (una vez)

En la instancia LAB:

- Instalar **Docker** y **Docker Compose v2** (si no están).
- Clonar el repo, por ejemplo:  
  `git clone https://github.com/ccruz0/crypto-2.0.git ~/automated-trading-platform`  
  (o la URL del repo que uses).

---

## 3. Token y .env.lab (Phase 1 del setup)

Seguir **docs/openclaw/LAB_SETUP_AND_VALIDATION.md** Phase 1:

- Crear `~/secrets/openclaw_token` (permiso 600) con el **fine-grained PAT** de GitHub (Contents R/W, Pull requests R/W, Metadata R).
- Crear `.env.lab` desde `.env.lab.example` en el clone; definir **OPENCLAW_TOKEN_PATH** (p. ej. `/home/ubuntu/secrets/openclaw_token`), **GIT_REPO_URL** y, si aplica, **OPENCLAW_IMAGE**.  
  No poner el token en `.env.lab`, solo la ruta al archivo.

---

## 4. Levantar OpenClaw

En el directorio del repo en LAB:

```bash
cd ~/automated-trading-platform
docker compose -f docker-compose.openclaw.yml up -d
docker compose -f docker-compose.openclaw.yml ps
docker compose -f docker-compose.openclaw.yml logs -f openclaw
```

Opcional: instalar el servicio systemd para que arranque tras reinicio (ver **docs/openclaw/DEPLOYMENT.md** §3).

---

## 5. Validar (Phase 2) y checklist de seguridad

- **Phase 2** de **LAB_SETUP_AND_VALIDATION.md**: probar push a rama `openclaw/*`, crear PR por API, comprobar que “add label” devuelve 403.
- Recorrer **docs/openclaw/FINAL_SECURITY_CHECKLIST.md** (token scope, path-guard, Docker isolation, etc.).

---

## 6. Imagen de OpenClaw

Si **OPENCLAW_IMAGE** no existe o no está definida: hay que construir/publicar la imagen (p. ej. en GHCR) o usar un Dockerfile en el repo y definir **OPENCLAW_IMAGE** en `.env.lab`. Ver **docs/openclaw/DEPLOYMENT.md** y **docs/openclaw/ARCHITECTURE.md**.

---

**Runbook paso a paso (copy-paste en LAB):** [RUNBOOK_OPENCLAW_LAB.md](RUNBOOK_OPENCLAW_LAB.md).

**Documentos de referencia:** [LAB_SETUP_AND_VALIDATION.md](LAB_SETUP_AND_VALIDATION.md), [DEPLOYMENT.md](DEPLOYMENT.md), [FINAL_SECURITY_CHECKLIST.md](FINAL_SECURITY_CHECKLIST.md), [ARCHITECTURE.md](ARCHITECTURE.md).

**Preflight (desde tu máquina):** `./scripts/aws/openclaw_lab_preflight.sh` — comprueba SSM, Docker, repo y .env.lab en LAB.
