# OpenClaw en https://dashboard.hilovivo.com/openclaw — Camino rápido

Para que OpenClaw funcione en la ruta pública necesitas **3 cosas en orden**.

**Validar en 1 comando (desde tu máquina, sin SSH):**
```bash
cd /path/to/automated-trading-platform
./scripts/openclaw/run_openclaw_diagnosis_local.sh
```
- **401** en `/openclaw/` y `/openclaw/ws` = proxy y upstream OK (solo pide Basic auth). Abre la URL en el navegador y usa las credenciales.
- **404** = falta bloque nginx. **504** = upstream no responde. El script imprime el **NEXT ACTION** según el caso.

---

## 1) Arrancar y validar OpenClaw en el LAB

**Desde tu máquina (con SSM):**
```bash
cd /Users/carloscruz/automated-trading-platform
./scripts/openclaw/run_openclaw_check_via_ssm.sh
```

**En el servidor LAB (sin SSM):**
```bash
cd /home/ubuntu/crypto-2.0
sudo bash scripts/openclaw/check_and_start_openclaw.sh
```

**Qué debe salir bien:**
- `systemctl status openclaw` → activo
- `curl -I` a `/openclaw/` en el LAB devuelve **200/302** (no 504)

---

## 2) Proxy Nginx en el host del Dashboard (PROD)

En la instancia donde corre el dashboard (PROD):

```bash
cd /home/ubuntu/crypto-2.0
sudo bash scripts/openclaw/fix_openclaw_proxy_prod.sh
sudo nginx -t
sudo systemctl reload nginx
```

**Resultado esperado:**
- `/openclaw/` → proxy a la IP privada del LAB
- `/openclaw/ws` → proxy WebSocket al LAB (puerto 8081)

---

## 3) Probar en el navegador

Abre **https://dashboard.hilovivo.com/openclaw**.

| Síntoma | Causa probable |
|--------|-----------------|
| **404** | Falta el bloque nginx o no se recargó nginx |
| **504** | LAB no responde o upstream IP/puerto incorrecto |
| **UI carga pero el chat no** + consola con `ws://localhost...` | Frontend de OpenClaw usa WebSocket local → ver paso 4 |
| **Placeholder** | Contenedor/OpenClaw no arrancado o ruta incorrecta |

---

## 4) Si el problema es WebSocket `ws://localhost`

**No se arregla en ATP.** Se arregla en el repo **ccruz0/openclaw** (frontend).

**Objetivo:**
- Eliminar `ws://localhost:8081`
- Usar WebSocket same-origin: `wss://dashboard.hilovivo.com/openclaw/ws`

Luego:
1. Build + push de **ghcr.io/ccruz0/openclaw**
2. Redeploy en LAB con el workflow **Build OpenClaw image** o el deploy SSM que ya tienes

---

## 5) Token de OpenClaw (autenticación)

En el LAB debe existir:

| Dónde | Qué |
|-------|-----|
| **Host** | Archivo montado: `/home/ubuntu/secrets/openclaw_token` (chmod 600) |
| **Contenedor** | Ruta de lectura: `/run/secrets/openclaw_token` |
| **Env** | En `.env.lab` (o `.env.openclaw`): `OPENCLAW_TOKEN_FILE=/run/secrets/openclaw_token` |

El token no va en el compose ni en env como valor; solo la ruta del archivo.

---

## Validación en 2 minutos (3 bloques + 1 cambio según resultado)

### 1) En el host del Dashboard (PROD)

```bash
cd /home/ubuntu/crypto-2.0

# A) ¿Está el bloque nginx de /openclaw y a qué IP apunta?
sudo nginx -T 2>/dev/null | sed -n '/openclaw/,/}/p' | sed -n '1,200p'

# B) ¿Responde el endpoint en PROD (por nginx)?
curl -sS -I https://dashboard.hilovivo.com/openclaw/ | head -n 20
curl -sS -I https://dashboard.hilovivo.com/openclaw/ws | head -n 20
```

| Resultado | Significado | Acción |
|-----------|-------------|--------|
| **404** en curl de `/openclaw/` | El bloque no está cargado o no se recargó nginx. | Ejecutar abajo: insertar bloque, `nginx -t`, `reload`. |
| **504** en `/openclaw/` | Nginx apunta a una IP/puerto que no responde. | Validar upstream desde PROD (IP/puerto del LAB). |
| **101** o **200** en `/openclaw/ws` | WebSocket proxy OK. | — |

**Si ves 404, ejecuta en PROD:**
```bash
cd /home/ubuntu/crypto-2.0
sudo bash scripts/openclaw/insert_nginx_openclaw_block.sh 172.31.3.214
sudo nginx -t
sudo systemctl reload nginx
```
(Sustituye `172.31.3.214` por la IP privada real del LAB si es distinta.)

---

### 2) En el host de OpenClaw (LAB)

```bash
cd /home/ubuntu/crypto-2.0
sudo systemctl status openclaw --no-pager -l | sed -n '1,120p'
sudo ss -lntp | egrep '(:8081|:8080|:3000|:80)\b' || true
curl -sS -I http://127.0.0.1:8081/ | head -n 20 || true
```

| Resultado | Significado | Acción |
|-----------|-------------|--------|
| openclaw **no activo** o **nada en 8081** | Servicio no arrancado o puerto equivocado. | Ejecutar abajo: `check_and_start_openclaw.sh`. |
| **200/302** en curl a 127.0.0.1:8081 | OpenClaw responde en LAB. | Si PROD da 504, el fallo es IP/puerto del upstream en nginx (PROD). |

**Si openclaw no está activo o no hay nada escuchando en 8081:**
```bash
cd /home/ubuntu/crypto-2.0
sudo bash scripts/openclaw/check_and_start_openclaw.sh
```

---

### 3) Si carga la UI pero falla el chat (WebSocket)

En el navegador, abre la **consola**. Si aparece `ws://localhost:8081` o similar:

- El fallo es **100% en el repo ccruz0/openclaw** (frontend).
- Ahí el WS debe ser same-origin: `wss://dashboard.hilovivo.com/openclaw/ws`.
- No se arregla en ATP; hay que hacer el patch en openclaw, build + push imagen, redeploy en LAB.

---

## Siguiente paso según síntoma

Si pegas las salidas de los bloques **1) y 2)** (PROD + LAB), con eso se puede decir el cambio exacto: IP del upstream, puerto, o si toca entrar al repo openclaw y hacer el patch del WebSocket.
