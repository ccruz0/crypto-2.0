# 2026-08-06 — /api/brief 503 upstream_unavailable

**Estado:** RESUELTO  
**Host:** dashboard-prod (EC2 EIP 52.220.32.147)  
**Proyecto:** `/home/ubuntu/crypto-2.0` (compose `automated-trading-platform`)  
**Fecha:** 2026-08-06

## Síntoma

- `https://dashboard.hilovivo.com/api/brief/*` respondía **503** con cuerpo tipo `upstream_unavailable` vía nginx.
- Backend en `127.0.0.1:8002` estaba healthy; el 503 público enmascaraba el error de aplicación (config brief ausente) al fallar/interceptar upstream según el proxy.

## Causa raíz

- Variables `BRIEF_*` (y `TELEGRAM_SESSION_PATH`) ausentes de `secrets/runtime.env` actual.
- Estaban presentes en `secrets/runtime.env.bak.brief20260731` (31-jul) y se habían perdido en el runtime actual (posterior a ese bak; runtime modificado 2026-08-05).
- Sin `BRIEF_API_KEY` / mailboxes path el endpoint brief queda no configurado; nginx enmascara el fallo como `upstream_unavailable`.

## Fix aplicado (2026-08-06)

1. Diff previo: solo restaurar claves faltantes desde el bak (sin sobrescribir otras, sin `GITHUB_TOKEN`).
2. Backup: `secrets/runtime.env.bak.pre-brief-restore-20260806030623`
3. Append a `secrets/runtime.env`:
   - `BRIEF_API_KEY` (restaurado)
   - `BRIEF_MAILBOXES_PATH=/app/secrets/brief_mailboxes.json`
   - `BRIEF_RATE_LIMIT_PER_MINUTE=30`
   - `TELEGRAM_SESSION_PATH=/data/telegram/hilovivo.session`
4. Verificado: `secrets/brief_mailboxes.json` existe; volumen monta `./secrets` → `/app/secrets`; sesión telegram en volumen `aws_trading_config_data`.
5. Recreate: `sudo docker compose --profile aws up -d --force-recreate backend-aws` (también recreó dependencia `postgres_hardened`; sin reinicio de host; sin cambios nginx).

## Verificación

| Check | Resultado |
|-------|-----------|
| Contenedor `backend-aws` | healthy; `BRIEF_API_KEY=SET` (len=64) |
| Local sin key `GET /api/brief/mail` | **401** unauthorized (ya no brief_not_configured) |
| Público `GET /api/brief/mail?hours=24` + `X-Brief-Key` | **200** (`truncated=true`, accounts presentes) |
| Público `GET /api/brief/calendar?days=2` + key | **200** (body: `ics_urls_missing` — `BRIEF_ICS_URLS` no estaba en el bak; no inventado) |
| Público `GET /api/brief/telegram` + key | **409** `telegram_session_missing` (aceptable según alcance) |

## Residual / follow-ups

- No hay cron/scheduler de morning brief en EC2 (crontab ubuntu/root sin entradas brief). El scheduler del agente sigue fuera de este host salvo que viva en otro sitio (Mac/Cursor scheduled task).
- Opcional: restaurar `BRIEF_ICS_URLS` si se quiere calendario poblado; no estaba en el bak del 31-jul.
- Opcional: login/sesión telegram para pasar de 409 a 200 en `/api/brief/telegram`.
- Asegurar que futuros renders de `runtime.env` (p.ej. `scripts/aws/render_runtime_env.sh`) no vuelvan a dropear `BRIEF_*`.

## No hecho (deliberado)

- Sin cambios de nginx.
- Sin reinicio del host.
- Sin restaurar `GITHUB_TOKEN`.
- Sin inventar cron de morning brief.
