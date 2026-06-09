# Cómo construir y subir la imagen OpenClaw a GHCR

> **Nota:** Este documento trata **GHCR / imagen OpenClaw** (LAB). No describe la autenticación del **backend** en EC2. Para deploy y Cursor bridge, ver **[`backend/docs/GITHUB_APP_AUTH.md`](../../backend/docs/GITHUB_APP_AUTH.md)**. Los tokens personales (`ghp_` / `github_pat_`) **no** son la vía por defecto para registry; preferir CI, imagen pública o `scripts/openclaw/ghcr_login_lab.md`.

La imagen `ghcr.io/your-org/openclaw:latest` es un **placeholder**. Para usarla en el LAB necesitas construir la imagen desde el **repositorio donde está el código de OpenClaw** y subirla a GitHub Container Registry (GHCR).

---

## Requisitos

- Repositorio con el **código fuente de OpenClaw** y un **Dockerfile** que exponga el servicio en el puerto **8080**.
- Cuenta GitHub con el repo (ej. `ccruz0/openclaw` o el repo donde esté el Dockerfile).
- Credenciales de registry para GHCR (preferir CI o token no personal; ver §3).

---

## 1. Dónde está el código de OpenClaw

Este repo (`crypto-2.0`; ruta canónica `/home/ubuntu/crypto-2.0` — ver [BACKEND_AWS_CANONICAL_REPO.md](../operations/BACKEND_AWS_CANONICAL_REPO.md)) **no** contiene el código ni el Dockerfile de OpenClaw. Solo tiene:

- `docker-compose.openclaw.yml` (usa una imagen ya construida)
- Documentación y scripts de despliegue

Tienes que tener (o clonar) el **repo donde se construye OpenClaw**. Si es un producto externo, puede ser un repo privado o de otro proveedor. Si es tuyo, será algo como `github.com/ccruz0/openclaw` o similar.

---

## 2. Construir la imagen (en la máquina donde tengas el repo de OpenClaw)

Sustituye `TU_USUARIO` por tu usuario de GitHub (ej. `ccruz0`) y `openclaw` por el nombre del repo si es distinto.

```bash
# En el directorio raíz del repo de OpenClaw (donde está el Dockerfile)
cd /ruta/al/repo/openclaw
docker build -t ghcr.io/TU_USUARIO/openclaw:latest .
```

Si el Dockerfile está en un subdirectorio:

```bash
docker build -t ghcr.io/TU_USUARIO/openclaw:latest -f path/to/Dockerfile .
```

---

## 3. Autenticación en GitHub Container Registry (GHCR)

Para `docker push` / `docker pull` en `ghcr.io`, preferir credenciales **no personales**:

1. **GitHub Actions** en el repo de OpenClaw: push con `secrets.GITHUB_TOKEN` del workflow (no es un PAT personal).
2. **Paquete público** en GHCR → el LAB puede hacer `docker pull` sin login.
3. **Privado:** ver **`scripts/openclaw/ghcr_login_lab.md`** en este repo (tokens `ghs_` u org; rechaza `ghp_` / `github_pat_`).

Login local (solo si hace falta):

```bash
echo "TU_TOKEN_REGISTRY" | docker login ghcr.io -u TU_USUARIO --password-stdin
```

**(Histórico / legacy):** Un PAT clásico con `write:packages` (`ghp_…`) se usaba a veces; **no** es la recomendación por defecto.

---

## 4. Subir la imagen a GHCR

```bash
docker push ghcr.io/TU_USUARIO/openclaw:latest
```

Si el paquete es privado, en GitHub: repo → **Packages** (o tu perfil → Packages) y comprobar que la imagen aparece. Opcional: en Package settings → **Change visibility** si quieres que sea pública para que el LAB pueda hacer pull sin auth.

---

## 5. Usar la imagen en el LAB

En el LAB, en `.env.lab`:

```bash
OPENCLAW_IMAGE=ghcr.io/TU_USUARIO/openclaw:latest
```

Si la imagen es **privada**, en el LAB hay que hacer login a GHCR antes del `docker compose up` (con un token que tenga al menos `read:packages`):

```bash
echo "TOKEN_CON_READ_PACKAGES" | sudo -u ubuntu docker login ghcr.io -u TU_USUARIO --password-stdin
```

Luego:

```bash
sudo -u ubuntu bash -c 'cd /home/ubuntu/crypto-2.0 && docker compose -f docker-compose.openclaw.yml up -d'
```

---

## Resumen rápido (ejemplo con usuario `ccruz0`)

```bash
# En tu Mac (o donde tengas el repo de OpenClaw)
cd ~/repos/openclaw   # o la ruta real
docker build -t ghcr.io/ccruz0/openclaw:latest .
# Login GHCR: preferir CI push; si hace falta login local, usar token no personal (ver ghcr_login_lab.md)
echo "TU_TOKEN_REGISTRY" | docker login ghcr.io -u ccruz0 --password-stdin
docker push ghcr.io/ccruz0/openclaw:latest

# En el LAB (.env.lab)
OPENCLAW_IMAGE=ghcr.io/ccruz0/openclaw:latest

# Si la imagen es privada, en el LAB primero (mismo enfoque no personal):
echo "TU_TOKEN_REGISTRY" | sudo -u ubuntu docker login ghcr.io -u ccruz0 --password-stdin
# Luego
sudo -u ubuntu bash -c 'cd /home/ubuntu/crypto-2.0 && docker compose -f docker-compose.openclaw.yml up -d'
```

---

## Si no tienes el repo/código de OpenClaw

- Si OpenClaw es un **producto de un tercero**, revisa su documentación para ver si publican una imagen en Docker Hub o GHCR y qué nombre usar en `OPENCLAW_IMAGE`.
- Mientras tanto puedes usar una **imagen placeholder** en el LAB para quitar el 504 (algo que escuche en 8080), por ejemplo:

  ```bash
  sudo docker run -d --name openclaw -p 8080:80 nginx:alpine
  ```

  Cuando tengas la imagen real de OpenClaw, paras ese contenedor y usas `OPENCLAW_IMAGE` + `docker compose up -d` como arriba.
