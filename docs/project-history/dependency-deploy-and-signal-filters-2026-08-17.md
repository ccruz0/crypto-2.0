# Dependencias, despliegues y filtros de señal — 2026-08-17

Registro de una sesión larga de mantenimiento. Documenta dos incidentes de
despliegue (ambos resueltos), un bug de lógica de señal (abierto), el estado
medido del pipeline de auto-ML, y varios hechos de arquitectura que no estaban
escritos en ningún sitio y que costaron tiempo redescubrir.

---

## Incidente: despliegue de backend bloqueado por conflicto de dependencias

**Estado:** RESUELTO
**Fecha de detección:** 2026-08-17
**Severidad:** media (producción nunca se rompió, pero se perdió la capacidad de desplegar)
**Detectado por:** humano (revisión de PRs de Dependabot)

### Síntoma

Tres PRs de dependencias de backend mergeadas en rápida sucesión dejaron
producción desincronizada de `main`. Al forzar el despliegue manual, el build
falló en la fase de imagen.

### Línea temporal

1. Se mergean #192 (alembic 1.13.3 → 1.18.5, `9a4b417`), #194
   (pydantic-settings 2.5.2 → 2.14.2, `8cbfcde`) y #195 (uvicorn 0.32.0 →
   0.51.0, `4dd9520`) con pocos minutos de diferencia.
2. Los tres disparan *Deploy backend*. El grupo de concurrencia
   `atp-prod-ec2-deploy` cancela los dos últimos:
   - run #267 (#192): Éxito, 5m 18s
   - run #268 (#194): Cancelado, 59s
   - run #269 (#195): Cancelado, 54s
   Mensaje: `Canceling since a higher priority waiting request for
   atp-prod-ec2-deploy exists`.
3. Producción queda corriendo solo el cambio de alembic, aunque `main` tiene los tres.
4. Se dispara el despliegue manual (run #270) para resincronizar. Falla de
   verdad, no por cancelación.

### Causa raíz

Conflicto real de dependencias transitivas:

```
ERROR: Cannot install -r requirements.txt (line 46), uvicorn[standard]==0.51.0
and websockets==10.4 because these package versions have conflicting dependencies.

The conflict is caused by:
  The user requested websockets==10.4
  alpaca-trade-api 3.1.1 depends on websockets<11 and >=9.0
  uvicorn[standard] 0.51.0 depends on websockets>=13.0; extra == "standard"
```

`backend/requirements.txt` fija `websockets==10.4` con un comentario explícito
de que `alpaca-trade-api` requiere `<11`. uvicorn 0.51.0 exige `>=13.0`.

### Resolución

Revert de uvicorn a `0.32.0` en `backend/requirements.txt` (commit `5ef7cb0`,
directo a `main`).

### Validación

Deploy run #271: Éxito en 5m 44s, sin rollback.

### Lección / guardrail

Producción nunca se rompió porque el fallo ocurre en la fase de build, antes de
tocar EC2 — el contenedor en vivo siguió sirviendo la imagen anterior. Lo
preocupante no fue el fallo sino la ventana: durante ese rato **no se podía
desplegar nada**. Si hubiera hecho falta un fix urgente de trading, habría
estado bloqueado.

Mergear varias PRs de backend seguidas provoca cancelaciones en cadena por el
grupo de concurrencia. Conviene espaciarlas o verificar el deploy después de
la última.

---

## Incidente: despliegue de frontend bloqueado por peer dependency

**Estado:** RESUELTO
**Fecha de detección:** 2026-08-17
**Severidad:** media (mismo perfil que el anterior)
**Detectado por:** humano

### Síntoma

Tras mergear #201, el workflow *Deploy frontend* falló en `Build and push image`
a los 16 segundos.

### Causa raíz

```
npm error ERESOLVE could not resolve
npm error While resolving: react-dom@19.2.7
npm error Found: react@19.2.0
npm error peer react@"^19.2.7" from react-dom@19.2.7
```

Dependabot subió `react-dom` a 19.2.7 pero dejó `react` en 19.2.0. react-dom
19.2.7 exige peer `react@^19.2.7`, así que `npm ci` falla.

Runs de frontend afectados:

| Run | PR | Duración | Resultado |
|-----|----|----------|-----------|
| #118 | #199 tsx | 1m 10s | Cancelado |
| #119 | #200 next | 3m 36s | Éxito |
| #120 | #201 react-dom | 1m 37s | Fallo (ERESOLVE) |

### Resolución

Revert del PR #201 vía PR #488.

Editar solo `package.json` no habría servido: el `Dockerfile` usa `npm ci`, que
exige que `package-lock.json` esté sincronizado. El revert devuelve ambos
ficheros a un estado consistente.

### Lección / guardrail

Para subir `react-dom` hay que subir `react` a la vez y regenerar el lock file
con `npm install` en local. Dependabot no lo hace solo cuando el peer está
pineado exacto.

---

## Patrón común de ambos incidentes, y su mitigación

Los dos fallos tienen la misma forma: **Dependabot actualizó un paquete sin
poder actualizar aquello con lo que tiene que ser compatible.**

- uvicorn subió sin poder subir `websockets`, bloqueado por `alpaca-trade-api`.
- react-dom subió sin subir `react`.

En ambos casos **los checks de CI pasaron en verde**, porque no construían la
imagen Docker. El fallo solo aparecía en el paso de despliegue, ya después del
merge.

**Mitigación aplicada:** nuevo workflow `.github/workflows/ci-docker-build.yml`
(PR #491, commit `2b83202`). Construye las dos imágenes en cada PR que toque
`requirements.txt`, `package.json`, `package-lock.json` o los Dockerfiles. Usa
el mismo `-f` y el mismo contexto de build que los workflows de despliegue.
Solo construye: no hace push a ECR, no toca EC2, no usa credenciales AWS, y no
comparte el grupo de concurrencia de producción.

Validado en el propio PR que lo introdujo: run #1 en verde, 2m 6s, ambas
imágenes construidas.

A partir de aquí, "checks en verde" también significa "la imagen se puede
construir", que antes no era cierto.

---

## Bug abierto: filtros de BUY calculados y descartados

**Estado:** ABIERTO — documentado, sin cambios de código
**Fecha de detección:** 2026-08-17
**Severidad:** por determinar (ver más abajo)
**Detectado por:** humano, investigando una alerta de GRAM_USD

Detalle completo en la issue **#489**. Resumen para el histórico:

`should_trigger_buy_signal()` evalúa cinco grupos de condiciones y devuelve
`should_buy` más cinco flags. `calculate_trading_signals()` solo recoge dos
(`rsi_ok`, `ma_ok`) y **nunca consulta `should_buy`**. Los grupos
`trendFilters`, `rsiConfirmation` y `candleConfirmation` se calculan y se
descartan.

Caso testigo, GRAM_USD el 2026-08-16 a las 17:04 WIB (precio 1.3375, MA200
1.34, RSI 27.0, estrategia Auto/Conservative): con los filtros aplicados
debería haber sido bloqueado por cuatro motivos distintos. Ninguno llegó a
aplicarse. La señal salió, y `system_core` la rechazó después con
`SYSTEM_CORE_MA200`.

El propio texto de la alerta contiene la contradicción: incluye
`Price 1.3375 ≤ MA200 1.34 (trend filter requires price above MA200)` y aun así
concluye `MA conditions met | Price valid`.

**Riesgo asimétrico:** `system_core_trade_guards.py` solo revalida RSI y MA200.
No revalida `require_ema10_above_ma50` ni `require_close_above_ema10`. Una
señal fantasma que pase esos dos filtros **se convierte en orden real**. GRAM
no se ejecutó solo porque falló justo el filtro que sí está duplicado en la capa
de ejecución.

**Por qué no se arregló:** el arreglo obvio (respetar los cinco flags) podría
apagar todas las señales BUY, porque la config horneada tiene `rsi.buyBelow: 30`
(exige RSI < 30) junto a `rsiConfirmation.rsi_cross_level: 30` (exige RSI ≥ 30),
mutuamente excluyentes. **Sin verificar contra la config viva** (ver sección de
arquitectura).

---

## Estado medido del pipeline de auto-ML

Datos tomados del run #15 de *Ops — Auto ML hybrid retrain* (2026-08-17 13:40,
Éxito en 10m 44s, lookback `DAYS=90`).

El pipeline **funciona y sí persiste datos**. Cruza intenciones de operación con
alertas:

```json
"intents_considered": 108,
"complete": 91,
"with_alert": 88,
"without_alert": 3,
"join_coverage_pct": 84.26,
"dropped": {
  "still_open": 7,
  "orphan_rejected_by_guards": 8,
  "missing_entry_order": 1,
  "protection_cancelled_no_exit": 1,
  "dry_run_order_id": 0,
  "missing_order_id": 0,
  "entry_not_filled": 0,
  "missing_entry_price": 0,
  "no_children": 0
}
```

Tres observaciones que explican por qué `auto` no ha mejorado:

1. **Volumen insuficiente.** 91 ejemplos completos en 90 días es
   aproximadamente uno al día. Un modelo entrenado con ~91 muestras no va a
   superar a las reglas de las que partió.

2. **El cron nunca promociona.** El workflow lo dice en su primera línea:
   *"Schedule: weekly dry-run only (never promotes current.joblib)"*. El cron
   (`0 5 * * 1`, lunes 05:00 UTC) corre siempre en dry-run. La promoción real
   requiere `workflow_dispatch` con `dry_run_only=false`, y no consta que se
   haya hecho.

3. **`param_version` sigue en 1** en `trading_config.json`, con
   `seed_from: swing-conservative`. Es decir, los parámetros siguen siendo los
   de la semilla.

Además, el gate ML en código (`apply_auto_ml_buy_gate`) está por defecto
desactivado: `AUTO_ML_ENABLED` default false, solo shadow log. **No verificado
qué valor tiene en el `.env` de producción.**

**Conexión con el bug anterior:** `orphan_rejected_by_guards: 8` son casos
descartados del dataset porque los guards los rechazaron — exactamente el
patrón GRAM. El bug de los filtros ignorados no solo genera ruido en Telegram;
también encoge y sesga el conjunto de entrenamiento del que depende que `auto`
mejore. Un 7% de los casos se pierde por ahí.

---

## Hechos de arquitectura confirmados esta sesión

Cosas que no estaban documentadas y costaron tiempo redescubrir.

### La config viva NO es la del repo

`docker-compose.yml` monta:

```yaml
- TRADING_CONFIG_PATH=/data/trading_config.json
volumes:
  - aws_trading_config_data:/data
```

`backend/trading_config.json` del repo es **solo la semilla horneada en la
imagen**. La configuración viva la escribe el backend en ese volumen persistente
cuando se guarda desde la UI de Signal Config, y **sobrevive a los despliegues**.

Consecuencia práctica: **editar la config por PR no cambia producción**.
Cualquier ajuste tiene que hacerse sobre la config viva.

Para leerla:

```bash
docker exec automated-trading-platform-backend-aws-1 cat /data/trading_config.json
```

(Relacionado: `strategy-config-persist-fix-2026-07-17.md`.)

### Los logs rotan en horas

Docker con driver `json-file`, `max-file: 3`, `max-size: 20m`, sin destino
externo tipo CloudWatch. En un bot verboso eso son horas, no días. Ya bloqueó
dos investigaciones: el incidente de SL/TP y la medición del impacto de los
filtros. Cualquier diagnóstico que dependa de logs hay que hacerlo **poco
después** del evento.

### Grupo de concurrencia compartido

`atp-prod-ec2-deploy` lo comparten *Deploy backend*, *Deploy frontend* y
*deploy_session_manager*, para que dos compose deploys no pisen el host a la
vez. Efecto secundario: merges seguidos producen cancelaciones en cadena.

### Auto-merge sin revisión humana

El repo **no tiene branch protection** (Settings → Branches: *"Classic branch
protections have not been configured"*). La GitHub App **Cursor** ejecuta un
*Cursor Approval Agent: Pull Request Router and Approver* que aprueba
automáticamente, y un workflow *Enable auto-merge* hace squash-merge en cuanto
pasan los checks.

Comentario textual del bot:

> Approved. Cursor Bugbot was not present after the first checks poll, so that
> signal was skipped. No approval policy required human review, and no reviewers
> were assigned.

Ese día se auto-mergearon sin revisión tres PRs de salto grande de versión que
se habían apartado deliberadamente:

| PR | Cambio | Checks |
|----|--------|--------|
| #193 | fastapi 0.115.0 → 0.141.1 | 8 de 10 |
| #196 | eslint 9.38.0 → 10.8.1 | 9 de 10 |
| #198 | typescript 5.9.3 → 7.0.2 | 9 de 10 |

### Comandos de build de referencia

Backend (contexto = raíz del repo):

```bash
docker build -f backend/Dockerfile.aws \
  --build-arg GIT_SHA="$SHA" \
  --build-arg BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -t "$IMAGE:$SHA" .
```

Frontend (contexto = `frontend/`):

```bash
docker build --build-arg BACKEND_URL=http://backend-aws:8002 \
  -f frontend/Dockerfile frontend
```

---

## Decisiones tomadas

| Decisión | Razón |
|----------|-------|
| Mantener el auto-merge activo | Se prefiere la automatización; el hueco real no era la revisión sino que los checks no construían la imagen. Se cerró con el job de docker build. |
| Revertir uvicorn en vez de relajar `websockets` | Relajar el pin habría tocado la compatibilidad con `alpaca-trade-api` sin probarla. Revertir vuelve a un estado conocido bueno. |
| No tocar los filtros de señal, solo documentar | El arreglo obvio podía apagar todas las señales BUY. Falta leer la config viva antes de decidir. |
| No mergear #197 sin validar | Está en verde, pero con checks anteriores al job de docker build. Mergearlo sin validar contradice lo que se acababa de construir. |

---

## Abierto al cierre de la sesión

- **#489** — bug de filtros ignorados. Necesita leer la config viva antes de decidir.
- **#197** — python-multipart, sin validar contra build real. Se desbloquea con
  `@dependabot rebase` (o cerrar y reabrir el PR) para que corra el check nuevo.
- **Volumen de datos de auto-ML** — 91 muestras en 90 días no da para aprender.
  Sin resolver.
- **Promoción del modelo** — el cron es dry-run permanente; nadie ha lanzado una
  promoción real.
- **Rotación de logs** — sigue en 3×20MB sin destino externo.
- **Rotación de la contraseña de Postgres** — procedimiento preparado, pendiente
  de ventana de bajo tráfico.
- **`business_rules_canonical.md`** — desactualizado. Define la regla canónica de
  BUY con cinco flags y no menciona `trendFilters`, `rsiConfirmation` ni
  `candleConfirmation`, que son posteriores. Tampoco contempla el gate de MA200
  en la capa de ejecución.
