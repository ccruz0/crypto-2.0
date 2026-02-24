# Verificación post-deploy (PROD = atp-rebuild-2026)

Después de un deploy a **main** (workflow "Deploy to AWS EC2") o tras cambiar **EC2_HOST** a `dashboard.hilovivo.com`, comprueba lo siguiente.

---

## 0. Comprobación automática (cada 6 h)

El workflow **Prod Health Check** (Actions → Prod Health Check) se ejecuta cada 6 horas y al dispararlo a mano. Comprueba que `https://dashboard.hilovivo.com/api/health` responda 200. Si falla, el job marca error y en el summary verás el código HTTP.

---

## 1. Desde el run de GitHub Actions

- **Actions** → último run de **Deploy to AWS EC2** → abrir el job.
- En los logs:
  - Debe aparecer **"EC2_HOST is reachable: dashboard.hilovivo.com"** (o el valor que uses).
  - Debe aparecer **"Public API reachable (HTTP 200)"** si el secret **API_BASE_URL** está definido.
  - No debe haber errores en el paso "Deploy to EC2" ni en "Verifying deployment health".

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
- [ ] Push a `main` o Run workflow **Deploy to AWS EC2**.
- [ ] En el run: paso "Deploy to EC2" en verde; "EC2_HOST is reachable"; "Public API reachable (HTTP 200)" si API_BASE_URL está definido.
- [ ] Local: `./scripts/aws/prod_status.sh` → PROD API OK.
- [ ] Navegador: https://dashboard.hilovivo.com carga el frontend.

---

## 6. Troubleshooting

| Síntoma | Qué hacer |
|--------|-----------|
| Deploy falla: "EC2_HOST is not reachable" | Comprobar que EC2_HOST en Secrets es correcto; que la instancia PROD está running; que el SG permite SSH (22) desde los IPs de GitHub Actions o que usas deploy por SSM (Deploy to AWS EC2 Session Manager). |
| Deploy OK pero "Public API" no 200 o timeout | Comprobar nginx y backend en PROD (si tienes SSM o SSH); que API_BASE_URL en Secrets sea la URL pública del API (p. ej. `https://dashboard.hilovivo.com/api`). |
| Dashboard no carga en el navegador | Comprobar DNS, certificado, y que nginx en PROD sirve el frontend en / y el backend en /api/. |
| SSM PROD = ConnectionLost | [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](RUNBOOK_SSM_PROD_CONNECTION_LOST.md): reboot instancia, luego diagnóstico si sigue perdido. |
| Guard/Sentinel fallan por SSM | Mismo runbook; hasta que SSM esté Online en PROD, esos workflows no podrán ejecutar comandos en la instancia. |

---

**Referencias:** [AWS_STATE_AUDIT.md](../audit/AWS_STATE_AUDIT.md) §8, [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](RUNBOOK_SSM_PROD_CONNECTION_LOST.md), [AWS_PROD_QUICK_REFERENCE.md](AWS_PROD_QUICK_REFERENCE.md).
