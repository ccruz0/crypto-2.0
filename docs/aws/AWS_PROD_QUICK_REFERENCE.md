# AWS PROD — Referencia rápida

**Última actualización:** 2026-02-24. Producción = atp-rebuild-2026. crypto 2.0 ignorada.

---

## Instancias

| Rol   | Nombre             | Instance ID           | IP pública     | SSM (último)   |
|-------|--------------------|-----------------------|----------------|----------------|
| PROD  | atp-rebuild-2026   | i-087953603011543c5   | 52.220.32.147  | ConnectionLost |
| LAB   | atp-lab-ssm-clean  | i-0d82c172235770a0d  | None           | Online         |

---

## GitHub (repo crypto-2.0)

| Secret / variable | Uso |
|-------------------|-----|
| **EC2_HOST**      | Host para deploy SSH (debe ser `dashboard.hilovivo.com` o IP de PROD). |
| **EC2_KEY**       | Clave SSH para ubuntu@EC2_HOST. |
| **API_BASE_URL**  | URL base del API (p. ej. `https://dashboard.hilovivo.com/api`). Usado en deploy y Prod Health Check. |
| **AWS_ACCESS_KEY_ID** / **AWS_SECRET_ACCESS_KEY** | Para workflows que usan SSM (deploy_session_manager, restart_nginx, Guard/Sentinel). |

---

## Scripts (desde repo)

| Script | Qué hace |
|--------|----------|
| `./scripts/aws/verify_prod_public.sh [URL]` | Curl a /api/health. Exit 0 si 200. |
| `./scripts/aws/prod_status.sh [URL]`       | API + SSM (si hay AWS CLI). Resumen en una ejecución. |
| `./scripts/aws/aws_audit_live.sh`          | Instancias, IAM, SGs, SSM. Requiere AWS CLI. |

---

## Workflows relevantes

| Workflow | Trigger | Qué hace |
|----------|---------|----------|
| Deploy to AWS EC2 | push main | Deploy por SSH a EC2_HOST; health check local + verificación API pública. |
| Deploy to AWS EC2 (Session Manager) | manual | Deploy por SSM a i-087953603011543c5 (PROD). |
| Restart nginx | manual | Reinicio nginx vía SSM en PROD. |
| **Prod Health Check** | cada 6 h + manual | Curl a dashboard.hilovivo.com/api/health; falla si no 200. |
| AWS Runtime Guard / Sentinel | push main / diario | Verificación runtime en PROD (requiere SSM). |

---

## Runbooks

| Doc | Cuándo usar |
|-----|-------------|
| [POST_DEPLOY_VERIFICATION.md](POST_DEPLOY_VERIFICATION.md) | Tras un deploy o al verificar que PROD responde. |
| [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](RUNBOOK_SSM_PROD_CONNECTION_LOST.md) | Cuando PROD (atp-rebuild-2026) tiene SSM ConnectionLost. |
| [../audit/AWS_STATE_AUDIT.md](../audit/AWS_STATE_AUDIT.md) | Auditoría estado, decisión PROD/LAB, comandos vivos. |
| [../openclaw/SIGUIENTE_PASOS_OPENCLAW.md](../openclaw/SIGUIENTE_PASOS_OPENCLAW.md) | Para desplegar OpenClaw en LAB. |

---

## Próximos pasos (acción inmediata)

1. **Verificar deploy:** Haz push a `main` y revisa en GitHub Actions que el workflow **Deploy to AWS EC2** termine en verde y que `https://dashboard.hilovivo.com` responda. Checklist detallado: [POST_DEPLOY_VERIFICATION.md](POST_DEPLOY_VERIFICATION.md).
2. **OpenClaw en LAB:** Cuando quieras, sigue [SIGUIENTE_PASOS_OPENCLAW.md](../openclaw/SIGUIENTE_PASOS_OPENCLAW.md).

---

## Siguientes pasos opcionales

1. **SSM en PROD:** seguir [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](RUNBOOK_SSM_PROD_CONNECTION_LOST.md) (reboot + diagnóstico) hasta PingStatus Online.
2. **OpenClaw en LAB:** seguir [docs/openclaw/SIGUIENTE_PASOS_OPENCLAW.md](../openclaw/SIGUIENTE_PASOS_OPENCLAW.md).
3. **Hardening SGs:** aplicar [RUNBOOK_ARCH_B_PROD_LAB](../audit/RUNBOOK_ARCH_B_PROD_LAB.md) (atp-prod-sg, atp-lab-sg) si se quiere segregar por SG.

---

## Registro (2026-02-24)

- PROD fijado en atp-rebuild-2026 (i-087953603011543c5); crypto 2.0 ignorada.
- EC2_HOST en GitHub = dashboard.hilovivo.com. Workflows deploy_session_manager y restart_nginx usan INSTANCE_ID = i-087953603011543c5.
- Scripts de la raíz y runbooks actualizados a PROD. Añadidos: verify_prod_public.sh, prod_status.sh, aws_audit_live.sh; workflow Prod Health Check; runbooks SSM PROD y post-deploy; referencia rápida y regla .cursor/rules/aws-prod-instance.mdc.
