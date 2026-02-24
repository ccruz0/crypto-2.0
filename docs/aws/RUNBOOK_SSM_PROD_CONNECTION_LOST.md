# Runbook: PROD SSM ConnectionLost (atp-rebuild-2026)

Cuando **PingStatus** de **i-087953603011543c5** (atp-rebuild-2026) es **ConnectionLost**, el agente SSM no está alcanzando el control plane.

**Estado conocido (2026-02-24):** En esta instancia SSM sigue en Connection lost tras reboot, reasignar IAM role, reiniciar agente, IMDSv2 Optional. El agente falla con "Retrieve credentials produced error". **Acceso recomendado:** usar **EC2 Instance Connect** (no Session Manager) — ver § "Acceso cuando SSM no funciona" abajo.

**Región:** ap-southeast-1

---

## 1. Comprobar estado

```bash
aws ssm describe-instance-information --region ap-southeast-1 \
  --filters "Key=InstanceIds,Values=i-087953603011543c5" \
  --query 'InstanceInformationList[0].{InstanceId:InstanceId,PingStatus:PingStatus,LastPingDateTime:LastPingDateTime}' \
  --output table
```

Si **PingStatus** = `ConnectionLost`, sigue abajo.

---

## 2. Reboot de la instancia (suele recuperar el agente)

A menudo ConnectionLost se debe a red transitoria o agente colgado. Un reboot suele bastar.

```bash
aws ec2 reboot-instances --region ap-southeast-1 --instance-ids i-087953603011543c5
```

Espera **2–3 minutos** y vuelve a comprobar:

```bash
aws ssm describe-instance-information --region ap-southeast-1 \
  --filters "Key=InstanceIds,Values=i-087953603011543c5" \
  --query 'InstanceInformationList[0].PingStatus' --output text
```

Si pasa a **Online**, ya puedes usar Session Manager. Si sigue **ConnectionLost**, pasa al paso 3.

---

## 3. Diagnóstico detallado

Si tienes otra forma de entrar a la instancia (p. ej. SSH porque el SG permite 22 desde tu IP):

- Ejecuta en la instancia los comandos de **docs/audit/SSM_SESSION_MANAGER_CONNECTIVITY_AUDIT.md** (§ "Commands to run on instance"): estado del agente, logs, IMDS, DNS, time sync.
- Revisa **docs/audit/RUNBOOK_VPC_ENDPOINTS_SSM.md** si usas VPC endpoints para SSM.

Si **no** tienes SSH ni Session Manager:

- Comprueba en consola: **EC2 → Instances → i-087953603011543c5** → **Security** → Outbound del SG: debe permitir **HTTPS (443)** a **0.0.0.0/0** (o a los prefijos de SSM/EC2Messages/SSMMessages).
- Comprueba **IAM**: la instancia debe tener el **instance profile** **EC2_SSM_Role** (o equivalente con **AmazonSSMManagedInstanceCore**).
- Si cambiaste recientemente SG, NACL o endpoints, revierte o corrige según la auditoría de conectividad.

---

## 4. Acceso cuando SSM no funciona (recomendado mientras PROD siga Connection lost)

1. **Security group** **sg-07f5b0221b7e69efe**: añadir regla **inbound** SSH (22), origen **My IP**.
2. **EC2** → **Instances** → **atp-rebuild-2026** → **Connect** → pestaña **EC2 Instance Connect** → **Connect**.
3. Se abre una terminal en el navegador; no hace falta .pem. Para cerrar el acceso cuando termines, quita la regla SSH del SG.

---

## 5. Tras recuperar SSM

Cuando **PingStatus** sea **Online**:

- Conéctate por **Session Manager**: EC2 → Instances → atp-rebuild-2026 → Connect → Session Manager.
- Re-ejecuta los comandos de **docs/aws/AWS_LIVE_AUDIT.md** §2 (docker ps, compose --profile aws ps, puertos) para dejar documentado el estado del stack PROD.

---

**Referencias:** docs/audit/SSM_SESSION_MANAGER_CONNECTIVITY_AUDIT.md, docs/audit/RUNBOOK_VPC_ENDPOINTS_SSM.md, docs/aws/AWS_LIVE_AUDIT.md.
