# Security Maintenance Checklist

Este documento define las **tareas de seguridad operativas** del proyecto. Está pensado para cambios **incrementales** y reproducibles.

---

## 0) Puntos clave (resumen)

- **Imágenes pineadas por digest** cuando sea posible.

- **Escaneos automáticos**: PRs (bloqueante HIGH/CRITICAL) y **Nightly** (solo informe).

- **Lock de dependencias** con `constraints.txt` (backend) y lockfiles (frontend).

- **Secrets fuera de las imágenes** (Docker secrets / variables).

- **Principio de mínimo privilegio** en contenedores (`cap_drop`, `no-new-privileges`, `read_only`).

---

## 1) Cadencias

### Semanal (operativa)

- [ ] Revisar estado de pipelines de seguridad (PRs y Nightly).

- [ ] Evaluar nuevas CVEs **HIGH/CRITICAL** (Trivy/Docker Scout).

- [ ] Verificar healthchecks de servicios (`docker compose ps` y logs).

- [ ] Comprobar backups DB (si están configurados) y restauración de prueba (sandbox).

### Mensual (mantenimiento)

- [ ] Regenerar `constraints.txt` con parches seguros (backend).

- [ ] Actualizar imágenes base a último **patch** (Node, Python, Postgres).

- [ ] Limpiar/actualizar `.trivyignore` (eliminar entradas viejas).

- [ ] Revalidar `.dockerignore` (evitar que entren secretos/artefactos).

- [ ] Revisar límites de recursos y endurecimiento en `docker-compose.yml`.

- [ ] Revisar dependabot/renovate y cerrar PRs de seguridad.

### Por release (previo a tag)

- [ ] Ejecutar escaneo manual de imágenes (local) y guardar reporte.

- [ ] Verificar que **no** haya secretos embebidos en imágenes.

- [ ] Generar SBOM y adjuntarlo al release.

- [ ] Documentar versiones de base image y dependencias críticas.

---

## 2) Comandos útiles

> **Nota:** Siempre anteponer `cd` antes de cada comando.

### 2.1 Trivy (local)

```bash
cd /Users/carloscruz/automated-trading-platform

trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 local/atp-frontend:ci || true

cd /Users/carloscruz/automated-trading-platform

trivy fs --severity HIGH,CRITICAL --ignore-unfixed --exit-code 0 .
```

### 2.2 Regenerar constraints (backend)

```bash
cd /Users/carloscruz/automated-trading-platform/backend

bash scripts/lock.sh

cd /Users/carloscruz/automated-trading-platform/backend

docker build --no-cache -t automated-trading-platform-backend:latest .
```

### 2.3 Reconstruir imágenes y escanear con Docker Scout (GUI)

- Abrir Docker Desktop → Images → seleccionar imagen → Scan.

### 2.4 Compose (arranque/verificación)

```bash
cd /Users/carloscruz/automated-trading-platform

docker compose up -d --build

cd /Users/carloscruz/automated-trading-platform

docker compose ps

cd /Users/carloscruz/automated-trading-platform

docker compose logs -f backend
```

---

## 3) Checklist técnico por componente

### 3.1 Frontend (Next.js)

- [ ] NODE_ENV=production en runtime.

- [ ] output: 'standalone' en next.config.js.

- [ ] Imagen multi-stage con usuario no root.

- [ ] .dockerignore evita node_modules, .env, .next/cache.

- [ ] Healthcheck HTTP (200 OK).

- [ ] No conexión directa a APIs externas (solo a endpoints internos/DB proxy).

### 3.2 Backend (FastAPI)

- [ ] Imagen multi-stage (wheels) + usuario no root.

- [ ] constraints.txt actualizado (último lock.sh).

- [ ] Healthcheck (socket o /healthz).

- [ ] Logs estructurados y timeouts razonables.

- [ ] No secretos en variables bakeadas en la imagen.

### 3.3 Base de datos (PostgreSQL)

- [ ] postgres:15-alpine (o patch reciente).

- [ ] POSTGRES_INITDB_ARGS=--auth=scram-sha-256.

- [ ] Secrets: POSTGRES_PASSWORD_FILE=/run/secrets/pg_password.

- [ ] Puerto no publicado si solo lo usa backend (red interna).

- [ ] Backups automatizados y test de restore (sandbox).

---

## 4) CI/CD (seguridad)

- [ ] Workflow PR con Trivy (.github/workflows/security-scan.yml) → falla si HIGH/CRITICAL.

- [ ] Workflow Nightly (security-scan-nightly.yml) → no falla, sube SARIF y artifacts.

- [ ] .trivyignore versionado con comentarios claros.

- [ ] Caché de buildx configurado (rendimiento).

- [ ] Posibilidad de sbom: build-push-action@v6 con sbom: true.

---

## 5) Gestión de findings

- [ ] Priorizar CRITICAL/HIGH explotables en runtime.

- [ ] Documentar mitigaciones temporales en .trivyignore con comentario y fecha.

- [ ] Crear issue para cada CVE que no se pueda parchear en el día.

---

## 6) Roles y responsables

- Security Champion: <nombre>

- Dev Frontend: <nombre>

- Dev Backend: <nombre>

- Ops/Infra: <nombre>

---

## 7) Historial y referencias

- Trivy CI (PR): .github/workflows/security-scan.yml

- Trivy Nightly: .github/workflows/security-scan-nightly.yml

- Ignore file: .trivyignore

- Lock deps: backend/scripts/lock.sh, constraints.txt

- Compose endurecido: docker-compose.yml

- DB hardened: docker/postgres/Dockerfile

---

