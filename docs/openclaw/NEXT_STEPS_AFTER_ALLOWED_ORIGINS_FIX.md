# Pasos siguientes tras el fix de allowedOrigins

El fix está aplicado en **dos sitios**:

1. **ATP (este repo):** wrapper con entrypoint que escribe `~/.openclaw/openclaw.json` y pasa `OPENCLAW_ALLOWED_ORIGINS`.
2. **OpenClaw (repo `~/openclaw`):** la app ahora lee `OPENCLAW_ALLOWED_ORIGINS` en `loadConfig`, incluye `https://dashboard.hilovivo.com` en los orígenes por defecto y hace log de `gateway.controlUi.allowedOrigins resolved: [N origins]`.

---

## 1. En el repo OpenClaw (`~/openclaw`)

```bash
cd /Users/carloscruz/openclaw
pnpm run build
# Si hay CI que publica la imagen:
git add -A && git status
git commit -m "fix(gateway): load OPENCLAW_ALLOWED_ORIGINS and default dashboard origin for non-loopback"
git push origin main
# Esperar a que la imagen se construya y se suba a GHCR (o construir y subir a mano).
```

---

## 2. (Opcional) Reconstruir el wrapper en ATP

Si usas la imagen wrapper `openclaw-with-origins` / `ghcr.io/ccruz0/openclaw:with-origins`, vuelve a construirla desde la nueva base:

```bash
cd /Users/carloscruz/crypto-2.0
docker build -f openclaw/Dockerfile.openclaw -t openclaw-with-origins:latest .
docker tag openclaw-with-origins:latest ghcr.io/ccruz0/openclaw:with-origins
docker push ghcr.io/ccruz0/openclaw:with-origins
```

---

## 3. En LAB

```bash
sudo docker pull ghcr.io/ccruz0/openclaw:with-origins
# O, si usas la imagen base directa (con el fix ya en la app):
# sudo docker pull ghcr.io/ccruz0/openclaw:latest

sudo docker stop openclaw 2>/dev/null || true
sudo docker rm openclaw 2>/dev/null || true
sudo docker run -d --restart unless-stopped \
  -p 8081:18789 \
  -e OPENCLAW_ALLOWED_ORIGINS=https://dashboard.hilovivo.com,http://localhost:18789,http://127.0.0.1:18789 \
  --name openclaw \
  ghcr.io/ccruz0/openclaw:with-origins

sudo docker logs openclaw --tail 100
```

---

## 4. Verificación en logs

Debe aparecer:

- `[openclaw-entrypoint] gateway.controlUi.allowedOrigins loaded (3 origins)`
- `gateway.controlUi.allowedOrigins resolved: [3 origins]`

Y **no** debe aparecer:

- `non-loopback Control UI requires gateway.controlUi.allowedOrigins`

Comando rápido:

```bash
docker logs openclaw 2>&1 | grep -E "allowedOrigins loaded|allowedOrigins resolved|non-loopback Control UI"
```

---

## 5. Resumen de cambios en OpenClaw (ya aplicados)

| Archivo | Cambio |
|---------|--------|
| `src/config/io.ts` | `applyAllowedOriginsEnvOverride()`: aplica `OPENCLAW_ALLOWED_ORIGINS` al config (y cuando no hay archivo). |
| `src/config/gateway-control-ui-origins.ts` | Por defecto se añade `https://dashboard.hilovivo.com` en `buildDefaultControlUiAllowedOrigins`. |
| `src/gateway/server.impl.ts` | Log: `gateway.controlUi.allowedOrigins resolved: [N origins]`. |
| `src/wizard/onboarding.gateway-config.test.ts` | Test actualizado para los 3 orígenes por defecto. |
