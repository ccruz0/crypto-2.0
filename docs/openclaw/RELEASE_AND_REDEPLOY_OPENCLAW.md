# Release and redeploy OpenClaw (production image)

Pasos finales para publicar la imagen desde ccruz0/openclaw y desplegarla en LAB. Validar en el navegador al terminar.

---

## 1. Publicar la imagen desde ~/openclaw

```bash
cd ~/openclaw
git add .
git commit -m "release: openclaw production image"
git push origin main
```

- En **GitHub Actions** (repo ccruz0/openclaw): confirmar que el workflow **docker_publish.yml** termina en verde.
- En **GHCR**: confirmar que existe la imagen **ghcr.io/ccruz0/openclaw:latest**.

---

## 2. Redeploy en LAB (puerto correcto)

El servicio dentro del contenedor escucha en **18789**. Mapeo: host 8081 → contenedor 18789.

Si `docker pull` falla con **error from registry: denied**, sigue [GHCR_ACCESS_LAB.md](./GHCR_ACCESS_LAB.md) (hacer público el package o hacer `docker login` en LAB).

```bash
docker pull ghcr.io/ccruz0/openclaw:latest
docker stop openclaw || true
docker rm openclaw || true
docker run -d --restart unless-stopped -p 8081:18789 --name openclaw ghcr.io/ccruz0/openclaw:latest
docker logs --tail=120 openclaw
```

---

## 3. Verificación rápida

**En LAB:**

```bash
docker inspect openclaw --format "Image={{.Config.Image}} Created={{.Created}}"
docker port openclaw
```

**En el navegador:**

- Abrir **https://dashboard.hilovivo.com/openclaw/**
- No debe aparecer "Placeholder".
- En consola del navegador: no debe aparecer `ws://localhost:8081`.
- En **Network → WS**: la conexión debe ser a `/openclaw/ws` (código 101).

---

## Si sigue saliendo placeholder

Casi siempre es una de estas dos cosas:

1. **El contenedor sigue con la imagen vieja**  
   Faltó `docker pull` o no se recreó el contenedor (`docker rm` + `docker run`).

2. **El puerto interno no es 18789**  
   Revisar `docker port openclaw` y los logs del contenedor; ajustar el mapeo:  
   `-p 8081:<PUERTO_INTERNO>`.
