# Runbook: OpenClaw en LAB (atp-lab-ssm-clean)

Pasos para dejar OpenClaw corriendo en la instancia LAB (i-0d82c172235770a0d). Requiere SSM Online (LAB lo tiene).

---

## 0. Conectar a LAB

- **AWS Console:** EC2 → Instances → **atp-lab-ssm-clean** → Connect → **Session Manager**.
- O desde tu máquina (con AWS CLI y permisos SSM):
  ```bash
  aws ssm start-session --target i-0d82c172235770a0d --region ap-southeast-1
  ```

---

## 1. Preparar el host (una vez)

En la sesión de LAB:

```bash
# Docker + Compose v2 (si no están)
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 2>/dev/null || true
sudo usermod -aG docker "$(whoami)"
# Cerrar sesión y volver a entrar para que docker funcione sin sudo, o usar: newgrp docker

# Clonar repo (si no existe)
cd /home/ubuntu
[ -d automated-trading-platform ] || git clone https://github.com/ccruz0/crypto-2.0.git automated-trading-platform
cd automated-trading-platform
git fetch origin main && git checkout main
```

---

## 2. Token de GitHub (Phase 1)

**Necesitas:** un **fine-grained PAT** con permisos: Contents (R/W), Pull requests (R/W), Metadata (R). Sin permisos de Admin/Secrets.

En LAB:

```bash
mkdir -p ~/secrets
chmod 700 ~/secrets
touch ~/secrets/openclaw_token
chmod 600 ~/secrets/openclaw_token

# Pegar el PAT cuando pida (no se verá)
read -r -s -p 'Paste GitHub fine-grained PAT: ' TOKEN
echo -n "$TOKEN" > ~/secrets/openclaw_token
unset TOKEN

# Comprobar permisos
ls -la ~/secrets/openclaw_token
# Debe ser: -rw------- 1 ubuntu ubuntu
test -r ~/secrets/openclaw_token && echo "OK: token readable"
```

---

## 3. Archivo .env.lab

En LAB, en el directorio del repo:

```bash
cd /home/ubuntu/automated-trading-platform
cp .env.lab.example .env.lab
chmod 600 .env.lab
```

Editar `.env.lab` (p. ej. `nano .env.lab`) y dejar algo como:

```bash
GIT_REPO_URL=https://github.com/ccruz0/crypto-2.0.git
OPENCLAW_TOKEN_PATH=/home/ubuntu/secrets/openclaw_token

# OBLIGATORIO: imagen de OpenClaw. Por defecto es un placeholder.
# Opción A: si tienes imagen en GHCR (reemplaza your-org por tu org/usuario):
OPENCLAW_IMAGE=ghcr.io/ccruz0/openclaw:latest
# Opción B: si construyes desde el repo, ver docs/openclaw/DEPLOYMENT.md §6 (build local)
# OPENCLAW_IMAGE=openclaw:local

OPENCLAW_BASE_BRANCH=main
OPENCLAW_LOG_LEVEL=INFO
```

**Importante:** no pongas el token en `.env.lab`, solo `OPENCLAW_TOKEN_PATH`. Comprobar:

```bash
grep -i token .env.lab
# Debe mostrar solo OPENCLAW_TOKEN_PATH=...
```

---

## 4. Levantar OpenClaw

```bash
cd /home/ubuntu/automated-trading-platform
docker compose -f docker-compose.openclaw.yml up -d
docker compose -f docker-compose.openclaw.yml ps
docker compose -f docker-compose.openclaw.yml logs -f openclaw
```

Si falla el `up` por "image not found": define una **OPENCLAW_IMAGE** válida en `.env.lab` (imagen publicada en GHCR o build local; ver DEPLOYMENT.md).

---

## 5. (Opcional) Arranque tras reinicio

```bash
sudo cp /home/ubuntu/automated-trading-platform/scripts/openclaw/openclaw.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable openclaw
sudo systemctl start openclaw
```

---

## 6. Validar (Phase 2) y seguridad

- **Phase 2:** [LAB_SETUP_AND_VALIDATION.md](LAB_SETUP_AND_VALIDATION.md) — push a rama `openclaw/*`, crear PR por API, comprobar que "add label" devuelve 403.
- **Checklist:** [FINAL_SECURITY_CHECKLIST.md](FINAL_SECURITY_CHECKLIST.md).

---

## Referencia rápida

| Qué | Dónde |
|-----|--------|
| **Continuar instalación** (apt ya OK) | [INSTALL_CONTINUE.md](INSTALL_CONTINUE.md) |
| Comandos para pegar en SSM | `./scripts/openclaw/print_lab_commands.sh` (desde el repo) |
| Setup token + .env | [LAB_SETUP_AND_VALIDATION.md](LAB_SETUP_AND_VALIDATION.md) Phase 1 |
| Imagen / build | [DEPLOYMENT.md](DEPLOYMENT.md) §6, §8 |
| Seguridad | [FINAL_SECURITY_CHECKLIST.md](FINAL_SECURITY_CHECKLIST.md) |
| Resumen pasos | [SIGUIENTE_PASOS_OPENCLAW.md](SIGUIENTE_PASOS_OPENCLAW.md) |

**Instance ID LAB:** `i-0d82c172235770a0d` (ap-southeast-1).
