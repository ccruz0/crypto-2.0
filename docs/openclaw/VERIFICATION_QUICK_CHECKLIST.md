# Verificación rápida — path-guard sin bypass

---

## 1) Confirmar que "path-guard" es obligatorio en el ruleset

**Tú en GitHub (no se puede hacer desde el repo):**

1. Repo → **Settings** → **Rules** → **Rulesets**
2. Abre **protect-main-production**
3. En **"Require status checks to pass"** debe aparecer:
   - **path-guard**
   - **nightly-trivy** (y los demás que tengas)
4. Si al limpiar checks quitaste **path-guard**, añádelo de nuevo y guarda.

No hay forma de comprobarlo desde el código; es solo configuración en la UI de GitHub.

---

## 2) Prueba real en ~2 minutos (sin OpenClaw)

**Objetivo:** PR que toca un path protegido → path-guard falla; aunque añadas a mano el label `security-approved`, sigue fallando.

**Comandos (desde el repo en tu máquina):**

```bash
cd /Users/carloscruz/crypto-2.0
git fetch origin main
git checkout -b test/path-guard-verify origin/main

# Tocar un path protegido (p. ej. un comentario en routes_control.py)
echo "" >> backend/app/api/routes_control.py
# o: añade una línea de comentario al final del archivo

git add backend/app/api/routes_control.py
git commit -m "test: verify path-guard fails (no bypass)"
git push -u origin test/path-guard-verify
```

Luego en GitHub: **Open a pull request** de `test/path-guard-verify` → `main`.

**Resultado esperado:**

- El check **Path Guard** corre y **falla** (rojo).
- Añade manualmente el label **security-approved** al PR.
- El check **sigue fallando** (no hay bypass por label).
- Para mergear tendrías que quitar el cambio del path protegido o hacer un override explícito del ruleset; no hay “saltarse” el check con el label.

---

## 3) Workflows: sin `issues: write` por defecto

**Comprobado en los YAML que tocamos:**

| Workflow | permissions | issues: write |
|----------|-------------|----------------|
| path-guard.yml | contents: read, pull-requests: read | No |
| dashboard-data-integrity.yml | contents: read, pull-requests: write | No |
| no-inline-secrets.yml | contents: read, pull-requests: read | No |
| audit-pairs.yml | contents: read, pull-requests: read | No |
| egress-audit.yml | contents: read, pull-requests: read | No |
| aws-runtime-guard.yml | contents: read, pull-requests: read | No |
| aws-runtime-sentinel.yml | contents: read, pull-requests: read | No |
| deploy_session_manager.yml | contents: read, pull-requests: read | No |
| restart_nginx.yml | contents: read, pull-requests: read | No |
| disable_all_trades.yml | contents: read, pull-requests: read | No |
| deploy.yml | contents: read, id-token: write (job) | No |
| nightly-integrity-audit.yml | contents: read | No |
| security-scan*.yml | contents, security-events, actions | No |

**Conclusión:** En todos hay `permissions` definido y **ninguno** tiene `issues: write`. Solo dashboard tiene `pull-requests: write` (para comentar en el PR).

---

## 4) Label `security-approved`

- **Opción simple:** En GitHub → Repo → **Labels** → borrar **security-approved** si ya no lo usas para nada.
- **Opción controlada:** Dejarlo; en CI **no tiene ningún efecto** (path-guard ya no mira labels). Es lo que tienes ahora.

---

## 5) path-guard.yml — revisión rápida

El contenido actual de `.github/workflows/path-guard.yml` está bien para cerrar el tema:

- **Trigger:** `pull_request` a `main`.
- **permissions:** `contents: read`, `pull-requests: read` (no puede añadir labels).
- **Lógica:** Solo lista de archivos cambiados y lista de paths protegidos; si hay intersección → `exit 1` con el mismo mensaje de error. No se lee `github.event.pull_request.labels` ni se menciona `security-approved`.
- **Paths protegidos:** Los mismos de siempre (routes_control, routes_manual_trade, routes_orders, crypto_com_trade, runtime, trading_guardrails, telegram_secrets, secrets/, .env.aws, etc.).

No hace falta cambiar nada en ese archivo para la verificación. Si más adelante quieres ampliar o acotar paths, solo se toca el array `PROTECTED` en el step "Check protected paths".

---

**Resumen:** Haz 1) en la UI (ruleset con path-guard obligatorio), 2) el PR de prueba tocando un path protegido y comprobando que el check falla con y sin label, y 3) ya está verificado en este doc. 4) y 5) son opcionales/confirmación.
