# Verificar consumo del token en el contenedor OpenClaw

Aunque el código de OpenClaw no esté en este repo, puedes inspeccionar el contenedor en LAB y, si tienes el repo fuente, auditar el código allí.

---

## Evaluación en tres niveles

| Nivel | Qué certifica | Certeza |
|-------|----------------|---------|
| **1 – Infraestructura** | Token solo por archivo, permisos, mount :ro, no root, FS read-only, sin env fallback, sin URL con token, sin SSM, sin logs del installer. | Ya cerrado en este repo → estándar enterprise. |
| **2 – Runtime (LAB)** | Env del contenedor solo tiene `OPENCLAW_TOKEN_FILE`; logs sin token/Authorization/Bearer. | Tranquilidad operativa si los pasos 1 y 2 siguientes pasan limpios. |
| **3 – Código fuente** | No fallback a GITHUB_TOKEN, no logs de headers, no token en URLs git, no escritura en workspace. | Certeza total solo auditar el repo fuente de OpenClaw. |

**Recomendación:** (1) Ejecutar pasos 1 y 2 en LAB; si pasan → infraestructura certificada. (2) Después, abrir el repo fuente de OpenClaw y ejecutar el prompt de [PROMPT_AUDIT_OPENCLAW_SOURCE.md](PROMPT_AUDIT_OPENCLAW_SOURCE.md) para el cierre completo. Hasta entonces no se puede afirmar garantía criptográfica al 100%, pero sí que **la infraestructura no introduce riesgo adicional**.

---

## 1) Auditoría rápida en LAB (sin tocar código)

En la instancia LAB (SSH):

```bash
cd /home/ubuntu/automated-trading-platform
docker compose -f docker-compose.openclaw.yml up -d
docker exec -it openclaw sh
```

Dentro del contenedor:

```bash
env | sort | egrep "OPENCLAW|GITHUB|GH_TOKEN|TOKEN"
```

**Esperado:** Solo debe aparecer `OPENCLAW_TOKEN_FILE=/run/secrets/openclaw_token`.  
**No** deben aparecer: `GITHUB_TOKEN`, `GH_TOKEN`.

Luego:

```bash
ls -la /run/secrets
ls -la /run/secrets/openclaw_token
```

**Esperado:** El archivo existe, es readable por el usuario del contenedor y no world-readable.

Salir del contenedor: `exit`.

---

## 2) Prueba “no loguea el token”

En LAB (fuera del contenedor):

```bash
cd /home/ubuntu/automated-trading-platform
docker compose -f docker-compose.openclaw.yml logs --tail=300 openclaw | egrep -i "token|authorization|bearer|ghp_|github_pat_" || true
```

**Esperado:** No aparece nada (salida vacía).

---

## 3) Inspección rápida dentro de la imagen (opcional)

Dentro del contenedor (`docker exec -it openclaw sh`):

```bash
grep -R --line-number -E "OPENCLAW_TOKEN_FILE|GITHUB_TOKEN|GH_TOKEN|Authorization|Bearer" / 2>/dev/null | head -n 200
```

No es exhaustivo, pero da pistas de dónde se usa el token. Puede tardar un poco.

---

## 4) Auditar el repo fuente de OpenClaw (Cursor)

Si tienes el repo donde se construye `ghcr.io/ccruz0/openclaw:latest`, abre ese repo en Cursor y usa el prompt en:

**[PROMPT_AUDIT_OPENCLAW_SOURCE.md](PROMPT_AUDIT_OPENCLAW_SOURCE.md)**

Ese archivo contiene el prompt listo para pegar y obtener un informe + parches mínimos.

---

## Resumen

| Tienes | Certeza | Acción |
|--------|---------|--------|
| Solo imagen (contenedor en LAB) | Parcial | Ejecutar 1, 2 y opcionalmente 3 en LAB. |
| Repo fuente de OpenClaw | Total | Ejecutar 1 y 2 en LAB + auditar con el prompt (4) en el repo fuente. |

Referencia: [AUDIT_TOKEN_CONSUMPTION.md](AUDIT_TOKEN_CONSUMPTION.md) (qué controla este repo).
