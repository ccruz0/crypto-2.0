# Cursor and OpenClaw audit prompts

Copy the prompt you need into Cursor (English) or into OpenClaw in the dashboard (Spanish).

---

## 1) Cursor prompt (English) — Instance + Architecture Consistency Audit

Paste this into Cursor to run the full audit in the repo.

```
You are working in the repo /Users/carloscruz/automated-trading-platform (crypto-2.0 / ATP).

Goal
- Read ALL documentation and configuration in this repo and produce an "Instance + Architecture Consistency Audit".
- Identify inconsistencies between: docs, scripts, nginx config, docker-compose, environment/secrets guidance, and what is actually deployed.

Context (facts)
- PROD instance: atp-rebuild-2026 (private 172.31.32.169, public 52.220.32.147) serves https://dashboard.hilovivo.com
- LAB instance: atp-lab-ssm-clean (private 172.31.3.214) runs OpenClaw on port 8080
- PROD nginx now proxies /openclaw/ to LAB private IP 172.31.3.214:8080 and public endpoint returns 401 Basic Auth (expected)
- Backend routes exist under /api/* (e.g. /api/orders/open, /api/orders/history). /openapi.json at root is NOT expected.

Tasks
1) Build a definitive "source of truth" table:
   - Instances (PROD/LAB/others), instance IDs if present in docs, private/public IP expectations, what runs where, and how to verify.
2) Scan the repo for any references to old OpenClaw upstream IPs (52.77.216.100) and any conflicting IPs or instance names.
   - Output the exact file paths and line numbers for each conflict.
3) Confirm nginx routing expectations:
   - / -> frontend
   - /api/ -> backend
   - /openclaw/ -> OpenClaw (LAB)
   Produce a short "expected nginx config" block.
4) Confirm Docker Compose expectations:
   - Which compose files and profiles run on PROD vs LAB
   - Which ports are bound to 127.0.0.1 and which must never be public
5) Confirm secrets handling:
   - Identify any docs or scripts that risk committing secrets (e.g. .telegram_key)
   - Confirm where secrets should live (ignored paths) and how they are injected on PROD/LAB.
6) Produce an actionable remediation plan:
   - A prioritized list of fixes (P0/P1/P2), each with:
     - what to change
     - exact file(s)
     - minimal diffs
     - verification command(s)

Deliverables (must create files in repo)
- docs/audit/INSTANCE_ARCHITECTURE_CONSISTENCY_AUDIT.md
- docs/runbooks/INSTANCE_SOURCE_OF_TRUTH.md

Do NOT change production secrets or broaden AWS security groups.
Prefer minimal diffs.
```

---

## 2) OpenClaw mission (Spanish) — paste inside https://dashboard.hilovivo.com/openclaw/

Paste this into the OpenClaw UI (after Basic Auth) so it audits the repo and deployment.

```
Leer los docs del repo, comparar con el despliegue esperado, devolver inconsistencias con archivos y líneas, y proponer plan de fixes.
```

**Extended version (if OpenClaw supports longer prompts):**

```
Misión: Auditar la documentación y la configuración del repo ATP (crypto-2.0) frente al despliegue real.

Hechos:
- PROD: atp-rebuild-2026 (172.31.32.169 / 52.220.32.147), sirve dashboard.hilovivo.com.
- LAB: atp-lab-ssm-clean (172.31.3.214), OpenClaw en 8080.
- Nginx en PROD ya hace proxy /openclaw/ a 172.31.3.214:8080; el endpoint público devuelve 401 Basic Auth.

Entregables:
1) Lista de inconsistencias (archivo + línea) entre docs, scripts, nginx y docker-compose.
2) Referencias a la IP antigua 52.77.216.100 con rutas exactas.
3) Plan de corrección priorizado (P0/P1/P2) con diffs mínimos y comandos de verificación.
```

---

**Reference:** [INSTANCE_ARCHITECTURE_CONSISTENCY_AUDIT.md](INSTANCE_ARCHITECTURE_CONSISTENCY_AUDIT.md), [INSTANCE_SOURCE_OF_TRUTH.md](../runbooks/INSTANCE_SOURCE_OF_TRUTH.md).
