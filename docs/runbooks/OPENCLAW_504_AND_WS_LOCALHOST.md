# OpenClaw 504 Gateway Time-out y ws://localhost:8081

**Síntomas:** Al abrir https://dashboard.hilovivo.com/openclaw/ aparece **504 Gateway Time-out** y en consola **WebSocket connection to 'ws://localhost:8081/' failed**.

---

## Causa del 504

Nginx en **PROD** hace proxy de `/openclaw/` a **LAB** (`172.31.3.214:8081`). El 504 significa que:

- PROD no puede conectar a LAB:8081 (connect timeout 30s), o  
- LAB acepta la conexión pero no responde a tiempo (read timeout 300s).

En la práctica suele ser que **el contenedor OpenClaw en LAB no está corriendo** o LAB no es alcanzable desde PROD.

---

## 1. Comprobar desde PROD

Con sesión en **PROD** (ubuntu@ip-172-31-32-169):

```bash
# ¿PROD llega a LAB:8081?
curl -sI --connect-timeout 5 http://172.31.3.214:8081/
```

- Si **timeout o connection refused**: en LAB el servicio no está escuchando o hay red/firewall entre PROD y LAB.
- Si **HTTP/1.1 200** (o 401): el upstream responde; entonces el 504 puede ser intermitente o por tiempo de respuesta (aumentar timeouts en nginx si hace falta).

---

## 2. Comprobar y levantar OpenClaw en LAB

Conectarte a **LAB** (instancia `i-0d82c172235770a0d`, IP privada 172.31.3.214). Desde tu Mac:

```bash
aws ssm start-session --target i-0d82c172235770a0d --region ap-southeast-1
```

En LAB:

```bash
# ¿Está el contenedor corriendo?
docker ps -a | grep -i openclaw

# ¿Responde el puerto 8081 en localhost?
curl -sI --connect-timeout 3 http://localhost:8081/
```

Si el contenedor **no está** o **no responde**:

```bash
docker pull ghcr.io/ccruz0/openclaw:latest
docker stop openclaw 2>/dev/null || true
docker rm openclaw 2>/dev/null || true
docker run -d --restart unless-stopped -p 8081:18789 --name openclaw ghcr.io/ccruz0/openclaw:latest
docker logs --tail=50 openclaw
```

Vuelve a probar desde PROD: `curl -sI --connect-timeout 5 http://172.31.3.214:8081/` y luego https://dashboard.hilovivo.com/openclaw/

---

## 3. Sobre ws://localhost:8081 en consola

- Si la **página principal** devuelve **504**, el HTML/JS de OpenClaw **no llega** al navegador; lo que ves es la página de error de nginx.
- El mensaje **WebSocket connection to 'ws://localhost:8081/' failed** puede venir de otro script (p. ej. del dashboard que embebe el iframe) o de una versión antigua/caché.
- Cuando el **504 esté resuelto** y se cargue la app real de OpenClaw, la app debería usar **wss://dashboard.hilovivo.com/openclaw/ws** (mismo origen). Si siguiera usando `ws://localhost:8081`, habría que revisar en el repo **ccruz0/openclaw** que `getOpenClawWsUrl()` use el origin de la página y no el fallback a localhost.

---

## Resumen

| Comprobación | Dónde   | Comando |
|-------------|---------|---------|
| ¿LAB:8081 responde? | PROD    | `curl -sI --connect-timeout 5 http://172.31.3.214:8081/` |
| ¿Contenedor OpenClaw arriba? | LAB     | `docker ps \| grep openclaw` y `curl -sI http://localhost:8081/` |
| Levantar OpenClaw   | LAB     | `docker run -d --restart unless-stopped -p 8081:18789 --name openclaw ghcr.io/ccruz0/openclaw:latest` |
