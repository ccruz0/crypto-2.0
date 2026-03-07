# OpenClaw iframe en blanco — diagnóstico

Cuando la pestaña del dashboard carga pero el iframe de OpenClaw está en blanco, suele ser uno de estos casos:

- El proxy `/openclaw/` en el **server 443** no existe → el iframe pide a Next.js y falla.
- El proxy existe pero **Basic Auth dentro del iframe** bloquea (el iframe queda en blanco hasta autenticarse en una pestaña normal).
- El proxy existe pero la **respuesta 401** no lleva los headers correctos (sin `always` no se aplican a 401) y el navegador bloquea el frame.

Sigue los pasos **en este orden**.

---

## 1) ¿OpenClaw funciona fuera del dashboard?

Abre en **una pestaña nueva**:

**https://dashboard.hilovivo.com/openclaw/**

**Esperado:**

- Primera vez: prompt de Basic Auth.
- Tras autenticarte: carga la UI de OpenClaw.

- **Si NO funciona** → sigue siendo un problema de config Nginx 443 (ver [FIX_OPENCLAW_308_REDIRECT.md](FIX_OPENCLAW_308_REDIRECT.md)).
- **Si ves 504** → upstream no alcanzable: [OPENCLAW_504_UPSTREAM_DIAGNOSIS.md](OPENCLAW_504_UPSTREAM_DIAGNOSIS.md). Run the 3 commands, paste the 3 outputs → one change.
- **Si SÍ funciona** → pasa al paso 2.

---

## 2) Funciona en pestaña nueva pero no dentro del dashboard

Es lo más habitual: el navegador no muestra bien el prompt de Basic Auth dentro del iframe.

**Solución:**

1. Autentícate **una vez** en la pestaña nueva (`/openclaw/`).
2. **Recarga** la pestaña del dashboard.

A menudo el iframe carga después de eso.

---

## 3) Si el iframe sigue en blanco: inspeccionar la petición del iframe

En la página del dashboard (donde está el iframe de OpenClaw):

1. Clic derecho dentro del hueco del iframe → **Inspect**.
2. **DevTools → Network**.
3. Localiza la petición a **/openclaw/** (o a la URL del iframe).

Verás algo como:

- **401** (auth no enviada en el iframe)
- **308/404** (sigue yendo al frontend, no al proxy)
- **200** pero bloqueado (CSP / X-Frame-Options)

Anota:

- **Status**
- **Response headers:** `content-security-policy`, `x-frame-options`, `www-authenticate`

Con eso se sabe en qué rama estás y el cambio mínimo. Si pegas status + esos 3 headers, se puede indicar exactamente qué tocar.

---

## 4) Comprobación en el servidor (sin suposiciones)

En el servidor Ubuntu (52.220.32.147):

```bash
curl -I https://dashboard.hilovivo.com/openclaw/
```

**Esperado:** `401 Unauthorized` desde Nginx.

Luego:

```bash
curl -I -u openclaw:TU_PASSWORD https://dashboard.hilovivo.com/openclaw/
```

**Esperado:** `200 OK`.

Si obtienes **308/404** en el primer `curl`, el bloque 443 sigue sin ser el correcto (mismo runbook [FIX_OPENCLAW_308_REDIRECT.md](FIX_OPENCLAW_308_REDIRECT.md)).

---

## 5) Arreglo habitual: que los headers se apliquen también en 401

Si el iframe se bloquea por la **respuesta 401** (sin headers que permitan embedding), hay que hacer que Nginx envíe los headers en **todas** las respuestas, incluidas las 401.

En el **server 443**, dentro de `location ^~ /openclaw/`:

1. Usar **`always`** en el CSP para que aplique a 401:

```nginx
add_header Content-Security-Policy "frame-ancestors 'self' https://dashboard.hilovivo.com" always;
```

2. (Opcional) Forzar que las respuestas generadas por Nginx (p. ej. 401) no bloqueen el frame:

```nginx
add_header X-Frame-Options "" always;
```

Recarga Nginx y prueba de nuevo:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## Resumen

| Qué ves | Acción |
|--------|--------|
| /openclaw/ en pestaña nueva no carga | Arreglar proxy en 443 ([FIX_OPENCLAW_308_REDIRECT.md](FIX_OPENCLAW_308_REDIRECT.md)) |
| Pestaña nueva OK, iframe en blanco | Autenticar en pestaña nueva y recargar dashboard |
| Iframe sigue en blanco | DevTools → Network → status y headers de /openclaw/ |
| 401 sin CSP/XFO correctos | Añadir `always` a add_header (y opcionalmente X-Frame-Options "") |
| 308/404 en curl | Bloque openclaw no está en el 443 correcto |

Si pegas el status y los 3 headers (`content-security-policy`, `x-frame-options`, `www-authenticate`) de la petición a `/openclaw/`, se puede decir en qué rama estás y el cambio exacto.
