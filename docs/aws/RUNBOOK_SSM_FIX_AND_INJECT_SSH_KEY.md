# Runbook: Arreglar SSM e inyectar clave SSH en EC2

Objetivo: poder entrar por SSH con tu clave actual (`~/.ssh/atp-rebuild-2026.pem`) cuando el key pair de AWS no coincide con el .pem local.

## Estado actual

- **Instancia:** `i-087953603011543c5` (52.220.32.147). AMI: Ubuntu 24.04 → usuario **ubuntu** (no ec2-user).
- **SG egress:** ya permite todo (0.0.0.0/0)
- **IAM:** rol `EC2_SSM_Role` con políticas SSM correctas
- **Ruta:** subred usa tabla principal con 0.0.0.0/0 → Internet Gateway
- **Problema:** SSM mostraba `ConnectionLost`; a veces el agente se recupera tras un reboot

## Paso 1: Reinicio (ya ejecutado)

Se ha ejecutado:

```bash
aws ec2 reboot-instances --instance-ids i-087953603011543c5
```

Espera **2–3 minutos** a que la instancia vuelva a estar en running y el agente SSM se registre.

## Paso 2: Comprobar SSM

```bash
aws ssm describe-instance-information --filters "Key=InstanceIds,Values=i-087953603011543c5" --query 'InstanceInformationList[0].PingStatus' --output text
```

Si sale `Online`, sigue al paso 3. Si sigue `ConnectionLost`, espera un poco más y repite.

## Paso 3 (alternativa): EC2 Instance Connect (cuando SSM no conecta)

La instancia es **Ubuntu 24.04** (usuario `ubuntu`). Puedes inyectar tu clave con Instance Connect (válida 60 s) y en la primera sesión añadirla a `authorized_keys`:

```bash
PUBKEY_FILE=$(mktemp)
ssh-keygen -y -f ~/.ssh/atp-rebuild-2026.pem > "$PUBKEY_FILE"
aws ec2-instance-connect send-ssh-public-key \
  --instance-id i-087953603011543c5 \
  --instance-os-user ubuntu \
  --availability-zone ap-southeast-1a \
  --ssh-public-key "file://$PUBKEY_FILE"
rm -f "$PUBKEY_FILE"
# Inmediatamente (tienes 60 s):
ssh -o IdentitiesOnly=yes -i ~/.ssh/atp-rebuild-2026.pem ubuntu@52.220.32.147 "mkdir -p ~/.ssh; chmod 700 ~/.ssh; echo '$(ssh-keygen -y -f ~/.ssh/atp-rebuild-2026.pem)' >> ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys"
```

## Paso 3b: Inyectar clave vía SSM (cuando SSM esté Online)

Obtén tu clave pública:

```bash
PUBKEY=$(ssh-keygen -y -f ~/.ssh/atp-rebuild-2026.pem)
```

Inyéctala en la instancia (usuario **ubuntu** en Ubuntu 24.04):

```bash
aws ssm send-command \
  --instance-ids i-087953603011543c5 \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[\"mkdir -p /home/ubuntu/.ssh\", \"chmod 700 /home/ubuntu/.ssh\", \"echo '$PUBKEY' >> /home/ubuntu/.ssh/authorized_keys\", \"chmod 600 /home/ubuntu/.ssh/authorized_keys\"]" \
  --query 'Command.CommandId' --output text
```

Anota el `CommandId` que devuelve y comprueba el resultado:

```bash
# Sustituye COMMAND_ID por el valor anterior
aws ssm get-command-invocation --command-id COMMAND_ID --instance-id i-087953603011543c5 --query '{Status:Status,StdOut:StandardOutputContent,StdErr:StandardErrorContent}'
```

Si `Status` es `Success`, prueba SSH (usuario **ubuntu** en esta instancia):

```bash
ssh -i ~/.ssh/atp-rebuild-2026.pem ubuntu@52.220.32.147
```

## Si SSM sigue sin conectar

1. **Revisar región:** todos los comandos deben usar la misma región que la instancia (p. ej. `ap-southeast-1`). Configura `AWS_DEFAULT_REGION` o `--region ap-southeast-1`.
2. **VPC endpoints (opcional):** si la instancia está en subred privada sin NAT, necesitas VPC endpoints para SSM (`com.amazonaws.ap-southeast-1.ssm`, `ec2messages`, `ssmmessages`). En tu caso la subred tiene IGW, no debería hacer falta.
3. **Consola EC2:** En la consola AWS → EC2 → Instancias → Seleccionar instancia → “Connect” → “Session Manager”. Si desde la consola tampoco conecta, el problema es del agente o de la red dentro de la cuenta.

## Resumen de comandos (copiar/pegar)

```bash
# 1) Esperar 2–3 min tras el reboot, luego comprobar SSM
aws ssm describe-instance-information --filters "Key=InstanceIds,Values=i-087953603011543c5" --query 'InstanceInformationList[0].PingStatus' --output text

# 2) Cuando salga "Online", inyectar clave (usuario ubuntu)
PUBKEY=$(ssh-keygen -y -f ~/.ssh/atp-rebuild-2026.pem)
aws ssm send-command --instance-ids i-087953603011543c5 --document-name "AWS-RunShellScript" --parameters "commands=[\"mkdir -p /home/ubuntu/.ssh\", \"chmod 700 /home/ubuntu/.ssh\", \"echo '$PUBKEY' >> /home/ubuntu/.ssh/authorized_keys\", \"chmod 600 /home/ubuntu/.ssh/authorized_keys\"]" --query 'Command.CommandId' --output text

# 3) Comprobar (sustituir COMMAND_ID)
aws ssm get-command-invocation --command-id COMMAND_ID --instance-id i-087953603011543c5

# 4) SSH (esta instancia es Ubuntu → usuario ubuntu)
ssh -i ~/.ssh/atp-rebuild-2026.pem ubuntu@52.220.32.147
```
