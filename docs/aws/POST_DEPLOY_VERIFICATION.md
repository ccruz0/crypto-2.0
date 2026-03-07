# Verificación post-deploy (PROD = atp-rebuild-2026)

Después de un deploy a **main** (workflow **Deploy to AWS EC2 (Session Manager)**) o tras cambiar configuración de PROD, comprueba lo siguiente.

---

## 0. Comprobación automática (cada 6 h)

El workflow **Prod Health Check** (Actions → Prod Health Check) se ejecuta cada 6 horas y al dispararlo a mano. Comprueba que `https://dashboard.hilovivo.com/api/health` responda 200. Si falla, el job marca error y en el summary verás el código HTTP.

---

## 1. Desde el run de GitHub Actions

- **Actions** → último run de **Deploy to AWS EC2 (Session Manager)** → abrir el job.
- En los logs:
  - Debe aparecer el deploy por SSM a la instancia PROD (i-087953603011543c5).
  - No debe haber errores en el paso "Deploy to EC2 using Session Manager".
  - Si usas el workflow Legacy SSH, busca "EC2_HOST is reachable" y "Public API reachable (HTTP 200)".

---

## 2. Verificación local (sin hacer deploy)

Desde tu máquina, con el repo clonado:

**Solo API:**
```bash
./scripts/aws/verify_prod_public.sh
```

**Estado resumido (API + SSM si tienes AWS CLI):**
```bash
./scripts/aws/prod_status.sh
```

Si el script termina con **OK** / **PROD API reachable**, la API pública de PROD responde.

---

## 3. Comprobar el dashboard en el navegador

- Abre **https://dashboard.hilovivo.com** y confirma que carga el frontend.
- Si tienes un endpoint de estado/health en la UI, comprueba que los datos se actualizan.

---

## 4. SSM en PROD (opcional)

Si necesitas Session Manager en **atp-rebuild-2026** y el estado es **ConnectionLost**:

- Sigue **docs/aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md** (reboot + diagnóstico).
- Cuando **PingStatus** sea **Online**, puedes re-ejecutar los comandos de **docs/aws/AWS_LIVE_AUDIT.md** §2 para documentar el estado del stack.

---

## 5. Checklist primer deploy (tras cambiar EC2_HOST)

- [ ] GitHub Secrets: **EC2_HOST** = `dashboard.hilovivo.com` (o IP de atp-rebuild-2026).
- [ ] Push a `main` (dispara **Deploy to AWS EC2 (Session Manager)**) o Run workflow manualmente.
- [ ] En el run: paso "Deploy to EC2 using Session Manager" en verde.
- [ ] Local: `./scripts/aws/prod_status.sh` → PROD API OK.
- [ ] Navegador: https://dashboard.hilovivo.com carga el frontend.

---

## 6. Troubleshooting

| Síntoma | Qué hacer |
|--------|-----------|
| Deploy falla (SSM) | Comprobar AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY; que la instancia PROD (i-087953603011543c5) tenga SSM Online. Si SSM no está disponible, usar workflow "Deploy to AWS EC2 (Legacy SSH)" (manual) con EC2_HOST y EC2_KEY. |
| Deploy OK pero "Public API" no 200 o timeout | Comprobar nginx y backend en PROD (si tienes SSM o SSH); que API_BASE_URL en Secrets sea la URL pública del API (p. ej. `https://dashboard.hilovivo.com/api`). |
| Dashboard no carga en el navegador | Comprobar DNS, certificado, y que nginx en PROD sirve el frontend en / y el backend en /api/. |
| SSM PROD = ConnectionLost | [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](RUNBOOK_SSM_PROD_CONNECTION_LOST.md): reboot instancia, luego diagnóstico si sigue perdido. |
| Guard/Sentinel fallan por SSM | Mismo runbook; hasta que SSM esté Online en PROD, esos workflows no podrán ejecutar comandos en la instancia. |

---

**Referencias:** [AWS_STATE_AUDIT.md](../audit/AWS_STATE_AUDIT.md) §8, [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](RUNBOOK_SSM_PROD_CONNECTION_LOST.md), [AWS_PROD_QUICK_REFERENCE.md](AWS_PROD_QUICK_REFERENCE.md).
