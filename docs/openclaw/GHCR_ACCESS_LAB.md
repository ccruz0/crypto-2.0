# Arreglar "denied" al hacer pull de OpenClaw en LAB

Si en LAB `docker pull ghcr.io/ccruz0/openclaw:latest` falla con:

```text
Error response from daemon: error from registry: denied
```

es porque el **package de la imagen** en GHCR es privado. Hay que cambiar la visibilidad del **package** (contenedor), no del repositorio.

**Importante:** En un fork, "Change visibility" en **Repository → Settings** está deshabilitado; eso es la visibilidad del *repo*. La imagen Docker es un **package** distinto; su visibilidad se cambia en la página del package.

---

## Opción A: Hacer el package público (recomendado para LAB)

1. Entra en **GitHub** con la cuenta **ccruz0**.
2. Ve a **tu perfil** (click en tu avatar arriba a la derecha) → **Your profile**.
3. En tu perfil, abre la pestaña **Packages** (o ve a `https://github.com/ccruz0?tab=packages`).
4. Haz click en el package **openclaw** (la imagen Docker publicada por el workflow).
5. En la página del package, a la derecha: **Package settings**.
6. Baja a **Danger Zone** → **Change visibility** → **Public** → confirma.

Después de esto, en LAB (sin login) debería funcionar:

```bash
docker pull ghcr.io/ccruz0/openclaw:latest
```

---

## Opción B: Mantener el package privado y hacer login en LAB

Si quieres dejar el package privado, en la instancia LAB hay que hacer login en GHCR antes del pull.

1. En GitHub: **Settings** → **Developer settings** → **Personal access tokens** → crea un token con al menos el scope **read:packages**.
2. En LAB (por SSM o SSH), una sola vez:

```bash
echo "TU_GITHUB_PAT" | docker login ghcr.io -u ccruz0 --password-stdin
```

Sustituye `TU_GITHUB_PAT` por el token. Para no dejar el token en la sesión, mejor usar un secret (por ejemplo AWS Secrets Manager o SSM Parameter Store) y leerlo en un script que llame a `docker login`.

Después de `docker login`, el mismo bloque de redeploy funcionará:

```bash
docker pull ghcr.io/ccruz0/openclaw:latest
docker stop openclaw || true
docker rm openclaw || true
docker run -d --restart unless-stopped -p 8081:18789 --name openclaw ghcr.io/ccruz0/openclaw:latest
docker logs --tail=120 openclaw
```

---

## Después de arreglarlo

Vuelve a ejecutar el redeploy en LAB (los comandos de la sección 2 de [RELEASE_AND_REDEPLOY_OPENCLAW.md](./RELEASE_AND_REDEPLOY_OPENCLAW.md)) y comprueba en el navegador **https://dashboard.hilovivo.com/openclaw/**.
