# OpenClaw — First run checklist

Sigue estos pasos después de desplegar la UI integrada (proxy + página /openclaw).

---

## 1. Desplegar cambios

- Código: `nginx/dashboard.conf`, frontend `src/app/openclaw/page.tsx`, docs en `docs/openclaw/`.
- Push a tu rama y desplegar (build frontend, copiar nginx config al servidor del dashboard).

---

## 2. En el servidor del dashboard (Basic Auth + Nginx)

```bash
# Crear archivo de contraseña (sustituir 'openclaw' por el usuario que quieras)
sudo htpasswd -c /etc/nginx/.htpasswd_openclaw openclaw
# Introducir contraseña cuando pida

# Comprobar y recargar Nginx
sudo nginx -t && sudo systemctl reload nginx
```

Si Nginx no tiene el config nuevo aún, copia `nginx/dashboard.conf` a `/etc/nginx/sites-available/` (o el path que uses) y activa el site antes de recargar.

---

## 3. Verificar hardening

- **LAB Security Group:** Puerto 8080 del LAB **no** debe estar abierto a 0.0.0.0/0. Solo el IP del servidor del dashboard (o tu VPC) si el proxy está en ese servidor.
- **CSP:** En el navegador, abre DevTools → pestaña Network → recarga https://dashboard.hilovivo.com/openclaw/ → selecciona la petición → Headers. Debe aparecer `Content-Security-Policy: frame-ancestors 'self' https://dashboard.hilovivo.com`.
- **APIs sensibles:** Desde el servidor del dashboard: `curl -I https://dashboard.hilovivo.com/openclaw/` (debe pedir auth 401 o devolver 200 si ya autenticado). O ejecuta el script: `./scripts/openclaw/verify_openclaw_ui.sh` (opcional: `BASE_URL=https://dashboard.hilovivo.com`).

---

## 4. Calibración (read-only)

1. Abre **https://dashboard.hilovivo.com/openclaw** (o la URL de tu dashboard + `/openclaw`).
2. Autentícate con el usuario/contraseña del htpasswd si lo pide.
3. En la UI de OpenClaw, pega el **mandato de calibración** (desde `docs/openclaw/MANDATES_AND_RULES.md`):

   ```
   Analyze the repository structure and produce a system architecture map without modifying any files.
   ```

4. Ejecuta. Comprueba que **no** se crean ramas, PRs ni cambios en el repo.

---

## 5. MANDATE #1 (Trading Execution Reliability)

1. En la misma UI de OpenClaw, pega el bloque completo de **MANDATE #1** del mismo doc (`MANDATES_AND_RULES.md`).
2. Ejecuta según las **OpenClaw operation rules** (solo rama `develop`, PRs solo a `develop`).
3. Revisa: informe de auditoría, plan de mejoras y PRs generados.

---

## Referencias

- Config proxy y Basic Auth: [OPENCLAW_UI_IN_DASHBOARD.md](OPENCLAW_UI_IN_DASHBOARD.md)
- Mandates y reglas: [MANDATES_AND_RULES.md](MANDATES_AND_RULES.md)
- Checklist producción: [OPENCLAW_UI_IN_DASHBOARD.md](OPENCLAW_UI_IN_DASHBOARD.md) §0
