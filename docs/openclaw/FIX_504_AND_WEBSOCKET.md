# 504 en /openclaw/ y WebSocket a localhost

## 504 Gateway Time-out

Significa: Nginx (Dashboard) **no puede conectar** al upstream OpenClaw en el LAB (`172.31.3.214:8080`).

### Pasos (en este orden)

**1. En el Dashboard (ubuntu@ip-172-31-32-169)** — comprobar conectividad al LAB:

```bash
curl -sv --max-time 5 http://172.31.3.214:8080/
```

- **Timeout** → problema de red: en el **Security Group del LAB** añadir **Inbound**: Custom TCP, puerto **8080**, origen = **IP privada del Dashboard** (`172.31.32.169`) o el Security Group del Dashboard.
- **Connection refused** → en el LAB no hay nada escuchando en 8080: levantar OpenClaw (`docker compose -f docker-compose.openclaw.yml up -d` y `ss -lntp | grep 8080`).
- **Respuesta HTTP** → el 504 no debería aparecer; si sigue en el navegador, recargar Nginx en el Dashboard: `sudo nginx -t && sudo systemctl reload nginx`.

**2. En el LAB** — asegurar que OpenClaw escucha en `0.0.0.0:8080`:

```bash
sudo ss -lntp | grep 8080
docker compose -f docker-compose.openclaw.yml ps
```

Si no hay proceso en 8080, ver [FIX_504_NOW.md](FIX_504_NOW.md) y [OPENCLAW_504_UPSTREAM_DIAGNOSIS.md](OPENCLAW_504_UPSTREAM_DIAGNOSIS.md).

---

## WebSocket `ws://localhost:8081` failed

Ese error sale en la consola del navegador cuando la **app OpenClaw** (dentro del iframe o en la pestaña) intenta conectar a `localhost:8081`. No está en el repo del Dashboard; viene del código/build de la app OpenClaw (p. ej. imagen `ghcr.io/ccruz0/crypto-2.0:openclaw`).

- Con el **placeholder** actual (solo HTTP en 8080), no hay WebSocket; el mensaje puede ser de otra pestaña, extensión o de una versión anterior de la app.
- Cuando uses la **app OpenClaw real** detrás del proxy, debe usar URLs relativas o la misma origen para WebSocket, por ejemplo:
  - `wss://dashboard.hilovivo.com/openclaw/...` (mismo host que la página), o
  - Variable de entorno en el build (p. ej. `NEXT_PUBLIC_WS_URL`) apuntando a la URL pública, no a `localhost:8081`.

Nginx ya tiene los headers de WebSocket (`Upgrade`, `Connection "upgrade"`); si la app deja de usar `localhost:8081` y usa la ruta bajo `/openclaw/`, el proxy funcionará.
