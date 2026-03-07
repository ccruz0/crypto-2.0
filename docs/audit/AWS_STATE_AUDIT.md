# Auditoría AWS — Estado actual (repositorio y documentación)

**Fecha:** 2026-02-24  
**Región:** ap-southeast-1  
**Alcance:** Inventario desde el repositorio (documentación, workflows, scripts). No se ejecutan comandos contra AWS; para estado vivo usar los comandos del Apéndice.

---

## 1. Resumen ejecutivo

| Área | Estado | Notas |
|------|--------|--------|
| **Documentación PROD/LAB** | Definida | docs/aws y docs/openclaw describen PROD (atp-rebuild-2026) y LAB (atp-lab-ssm-clean). |
| **Instancias documentadas** | 3 referencias | atp-rebuild-2026, atp-lab-ssm-clean, "crypto 2.0". |
| **Consistencia CI vs docs** | Alineado | Deploy/restart por SSM apuntan a **atp-rebuild-2026** (i-087953603011543c5). crypto 2.0 ignorada. |
| **Scripts locales** | Alineados a PROD | Scripts de deploy/SSM usan i-087953603011543c5 (atp-rebuild-2026). |
| **Runtime Guard/Sentinel** | PROD correcto | runtime-history usa i-087953603011543c5 (atp-rebuild-2026). |
| **Última auditoría viva** | 2026-02-22 | docs/aws/AWS_LIVE_AUDIT.md; PROD con SSM ConnectionLost, LAB OK. |

**Decisión (2026-02-24):** Producción = **atp-rebuild-2026** (i-087953603011543c5). **crypto 2.0** (i-08726dc37133b2454) debe ignorarse; los workflows de deploy/restart apuntan a atp-rebuild-2026. EC2_HOST en GitHub = `dashboard.hilovivo.com`. Crypto 2.0 ya no figura entre instancias en ejecución (solo PROD + LAB).

---

## 2. Inventario de instancias (según documentación)

| Nombre / ID | Rol documentado | Tipo | IP pública | SG documentado | IAM |
|-------------|------------------|------|------------|----------------|-----|
| **atp-rebuild-2026** (i-087953603011543c5) | PROD | t3.small | 52.77.216.100 | sg-07f5b0221b7e69efe (launch-wizard-6) | EC2_SSM_Role |
| **atp-lab-ssm-clean** (i-0d82c172235770a0d) | LAB | t2.micro | None | sg-021aefb689b9d3c0e (atp-lab-sg2) | EC2_SSM_Role |
| **crypto 2.0** (i-08726dc37133b2454) | **Ignorar** (no usar para PROD) | — | (varies) | — | — |

- **VPC:** vpc-09930b85e52722581  
- **Subnets:** PROD subnet-0f4a20184f9106c6c; crypto 2.0 subnet-05dfde4f4da3a8887.

Referencias: docs/aws/AWS_LIVE_AUDIT.md, docs/aws/AWS_ARCHITECTURE.md, docs/audit/RUNBOOK_ARCH_B_PROD_LAB.md.

---

## 3. Uso de instance IDs en el repositorio

### 3.1 GitHub Actions (CI)

| Workflow | Variable / valor | Instance ID | Rol esperado (docs) |
|----------|------------------|-------------|----------------------|
| deploy.yml | EC2_HOST (secret) | No hardcoded | Debería ser PROD (DNS/IP de atp-rebuild-2026 o Elastic IP) |
| deploy_session_manager.yml | INSTANCE_ID | **i-087953603011543c5** | Deploy vía SSM → **atp-rebuild-2026 (PROD)** |
| restart_nginx.yml | INSTANCE_ID | **i-087953603011543c5** | Restart nginx → **atp-rebuild-2026 (PROD)** |
| aws-runtime-guard.yml | (script) | scripts/aws_runtime_verify.py | Runtime-history apunta a i-087953603011543c5 (PROD) |
| aws-runtime-sentinel.yml | (script) | scripts/aws_runtime_verify.py | Idem |

Conclusión: **Deploy y restart por SSM en CI apuntan a atp-rebuild-2026 (PROD).** crypto 2.0 ignorada.

### 3.2 Scripts en raíz del repo

- Los scripts de deploy/verificación/SSM usan **INSTANCE_ID="i-087953603011543c5"** (atp-rebuild-2026, PROD).
- Excepción: `scripts/aws/inject_ssh_key_via_ssm.sh` usa por defecto **i-087953603011543c5** (atp-rebuild-2026).

### 3.3 Documentación y runbooks

- docs/aws/*, docs/audit/RUNBOOK_ARCH_B_PROD_LAB.md, RUNBOOK_SSM_FIX, RUNBOOK_VPC_ENDPOINTS_SSM, EGRESS_A1: referencian **i-087953603011543c5** (PROD) e **i-0d82c172235770a0d** (LAB).
- RUNBOOK_ARCH_B menciona "crypto 2.0" (i-08726dc37133b2454) como instancia a reutilizar o sustituir por una nueva LAB.

---

## 4. Estado según última auditoría viva (2026-02-22)

Fuente: docs/aws/AWS_LIVE_AUDIT.md.

| Instancia | SSM (audit) | Stack ATP | Conformidad |
|-----------|-------------|-----------|-------------|
| atp-rebuild-2026 | ConnectionLost | No verificado (sin SSM) | Parcial |
| atp-lab-ssm-clean | Online | No hay stack; correcto para LAB | Conformante |

- PROD no pudo verificarse en runtime (SSM no alcanzable).
- LAB: sin stack de producción, sin IP pública, SSM OK.

---

## 5. OpenClaw y LAB

- **Arquitectura:** OpenClaw solo en LAB; sin secretos de prod; egress restringido (GitHub, DNS, IMDS).
- **Estado en repo:** docker-compose.openclaw.yml, .env.lab.example, systemd service y path-guard listos.
- **Estado en AWS:** No se sabe desde el repo si en atp-lab-ssm-clean está desplegado OpenClaw; la auditoría viva solo confirma que no hay stack ATP (no comprueba contenedor OpenClaw).
- **Nombre LAB actual:** atp-lab-ssm-clean (i-0d82c172235770a0d). RUNBOOK_ARCH_B opcionalmente crea una instancia llamada atp-lab-openclaw; en ese caso sería la instancia LAB en lugar de atp-lab-ssm-clean.

---

## 6. Hallazgos y recomendaciones

### 6.1 Crítico: alineación PROD en CI — **RESUELTO**

- **Decisión:** Producción = **atp-rebuild-2026** (i-087953603011543c5). crypto 2.0 se ignora.
- **Acción realizada:** deploy_session_manager.yml y restart_nginx.yml usan **INSTANCE_ID: i-087953603011543c5** (atp-rebuild-2026). Asegurar que el secret **EC2_HOST** en deploy.yml apunte al hostname o IP de atp-rebuild-2026 (o su Elastic IP/DNS).

### 6.2 SSM en PROD

- **Hallazgo:** En la última auditoría, atp-rebuild-2026 tenía SSM ConnectionLost.
- **Acción:** Seguir docs/audit/SSM_SESSION_MANAGER_CONNECTIVITY_AUDIT.md y RUNBOOK_VPC_ENDPOINTS_SSM si aplica; restaurar conectividad SSM y volver a ejecutar los comandos de verificación de docs/aws/AWS_LIVE_AUDIT.md §2.

### 6.3 Security groups y runbook ARCH B

- **Hallazgo:** RUNBOOK_ARCH_B propone atp-prod-sg y atp-lab-sg; la auditoría viva sigue mostrando launch-wizard-6 (PROD) y atp-lab-sg2 (LAB). No se verifica desde el repo si los SGs del runbook están creados/asignados.
- **Acción:** Ejecutar los comandos del Apéndice (describe-instances, describe-security-groups) y, si se adopta ARCH B, aplicar las secciones 2 y 3 del runbook.

### 6.4 Scripts en raíz

- **Hallazgo:** Muchos scripts tienen INSTANCE_ID fijo a crypto 2.0.
- **Acción:** Si PROD pasa a ser únicamente atp-rebuild-2026, considerar variable de entorno (por ejemplo AWS_INSTANCE_ID) o un único lugar de configuración (por ejemplo ops/inventory_env_vars o secret en CI) y actualizar scripts críticos para no hardcodear el ID.

### 6.5 OpenClaw en LAB

- **Hallazgo:** No hay evidencia en el repo de que OpenClaw esté desplegado en atp-lab-ssm-clean.
- **Acción:** Si se quiere OpenClaw en LAB, seguir docs/openclaw/LAB_SETUP_AND_VALIDATION.md y DEPLOYMENT.md en la instancia atp-lab-ssm-clean; luego ejecutar FINAL_SECURITY_CHECKLIST.

---

## 7. Checklist de verificación (decisión humana + comandos vivos)

- [x] **Definir instancia de producción:** atp-rebuild-2026 (crypto 2.0 ignorada).
- [x] **Alinear CI:** INSTANCE_ID en deploy_session_manager.yml y restart_nginx.yml = i-087953603011543c5 (atp-rebuild-2026).
- [ ] **Restaurar SSM en atp-rebuild-2026** (si es PROD) y re-ejecutar comandos de AWS_LIVE_AUDIT §2.
- [ ] **Ejecutar comandos del Apéndice** con AWS CLI para listar instancias, SSM e IAM/SGs y actualizar esta auditoría con resultados.
- [ ] **Opcional:** Aplicar RUNBOOK_ARCH_B (atp-prod-sg, atp-lab-sg, roles) si se confirma la arquitectura de dos instancias (PROD + LAB).
- [ ] **Opcional:** Desplegar y validar OpenClaw en LAB según docs/openclaw.

---

## 8. Última ejecución viva (aws_audit_live.sh)

**Fecha:** 2026-02-24

| Instancia            | Tipo      | IP pública     | SSM          | IAM            | SG                    |
|----------------------|-----------|----------------|--------------|----------------|------------------------|
| atp-rebuild-2026     | t3.small  | 52.220.32.147  | ConnectionLost | EC2_SSM_Role | sg-07f5b0221b7e69efe   |
| atp-lab-ssm-clean    | t2.micro  | None           | Online       | EC2_SSM_Role   | sg-021aefb689b9d3c0e  |
| crypto 2.0           | —         | —              | (no en lista)| —              | —                      |

**Verificación tras actualizar EC2_HOST:** (1) Hacer un push a `main` o disparar el workflow "Deploy to AWS EC2" y comprobar en los logs que la conexión SSH es a `dashboard.hilovivo.com`; el workflow ahora verifica también la API pública si API_BASE_URL está definido. (2) Si quieres SSM en PROD: **docs/aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md** (reboot + diagnóstico); si persiste, docs/audit/SSM_SESSION_MANAGER_CONNECTIVITY_AUDIT.md.

---

## Apéndice A: Comandos para auditoría viva (ejecutar con AWS CLI)

Región: `ap-southeast-1`. Requieren credenciales con permisos EC2 + SSM de solo lectura.

```bash
# 1) Listar instancias en ejecución
aws ec2 describe-instances --region ap-southeast-1 \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[*].Instances[*].[InstanceId,Tags[?Key==`Name`].Value|[0],InstanceType,PrivateIpAddress,PublicIpAddress,State.Name]' \
  --output table

# 2) Detalle de instancias (IAM, security groups)
aws ec2 describe-instances --region ap-southeast-1 \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[*].Instances[*].{Id:InstanceId,Name:Tags[?Key==`Name`]|[0].Value,IamProfile:IamInstanceProfile.Arn,SecurityGroups:SecurityGroups[*].[GroupId,GroupName]}' \
  --output json

# 3) Estado del agente SSM (todas las instancias gestionadas por SSM)
aws ssm describe-instance-information --region ap-southeast-1 \
  --query 'InstanceInformationList[*].{InstanceId:InstanceId,PingStatus:PingStatus,AgentVersion:AgentVersion}' \
  --output table

# 4) Filtrar solo las tres instancias conocidas
aws ssm describe-instance-information --region ap-southeast-1 \
  --filters "Key=InstanceIds,Values=i-087953603011543c5,i-0d82c172235770a0d,i-08726dc37133b2454" \
  --query 'InstanceInformationList[*].{InstanceId:InstanceId,PingStatus:PingStatus}' \
  --output table

# 5) Security groups (sustituir por los IDs actuales si cambian)
aws ec2 describe-security-groups --region ap-southeast-1 \
  --group-ids sg-07f5b0221b7e69efe sg-021aefb689b9d3c0e \
  --query 'SecurityGroups[*].{GroupId:GroupId,GroupName:GroupName,Inbound:IpPermissions,Egress:IpPermissionsEgress}' \
  --output json
```

Después de ejecutarlos, actualizar la tabla de §2 con los IDs/SGs reales si difieren y anotar en §4 el estado SSM actual.

---

## Apéndice B: Referencias

| Documento | Contenido |
|-----------|------------|
| docs/aws/AWS_ARCHITECTURE.md | Arquitectura objetivo, roles, SSM |
| docs/aws/AWS_LIVE_AUDIT.md | Última auditoría viva (2026-02-22) |
| docs/aws/README.md | Dashboard runtime, Guard/Sentinel |
| docs/audit/RUNBOOK_ARCH_B_PROD_LAB.md | Aislamiento PROD/LAB, SGs, IAM |
| docs/openclaw/ARCHITECTURE.md | OpenClaw en LAB, rutas protegidas |
| docs/openclaw/DEPLOYMENT.md | Despliegue OpenClaw, .env.lab |
| docs/audit/SSM_SESSION_MANAGER_CONNECTIVITY_AUDIT.md | Diagnóstico SSM |
