# LAB: Disco lleno y redeploy de OpenClaw

Cuando en LAB el `docker pull ghcr.io/ccruz0/openclaw:latest` falla con **no space left on device**, el volumen raíz (6.8G) es insuficiente para extraer la imagen. Este runbook describe cómo ampliar el disco y volver a desplegar.

- **Instancia LAB:** `i-0d82c172235770a0d` (atp-lab-ssm-clean)
- **Región:** `ap-southeast-1`

---

## 1. Diagnóstico rápido (opcional)

Desde tu máquina:

```bash
aws ssm send-command \
  --instance-ids i-0d82c172235770a0d \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["df -h /","docker system df"]' \
  --region ap-southeast-1 \
  --query 'Command.CommandId' --output text
# Luego: aws ssm get-command-invocation --command-id <ID> --instance-id i-0d82c172235770a0d --region ap-southeast-1
```

---

## 2. Aumentar el tamaño del volumen EBS (AWS Console)

1. **EC2 → Volumes.** Busca el volumen asociado a la instancia `i-0d82c172235770a0d` (por ejemplo 8 GiB).
2. Selecciona el volumen → **Actions → Modify volume**.
3. Aumenta **Size** (por ejemplo a **20 GiB**) → **Modify**.
4. Espera a que el estado del volumen sea **completed** (unos segundos o pocos minutos).

---

## 3. Extender la partición y el sistema de archivos (dentro de LAB)

Conectarte por SSM y ejecutar (la instancia suele usar partición única en el dispositivo NVMe/EBS):

```bash
aws ssm start-session --target i-0d82c172235770a0d --region ap-southeast-1
```

Dentro de LAB:

```bash
# Ver bloque del disco raíz (ej. /dev/nvme0n1 o /dev/xvda)
lsblk
sudo growpart /dev/nvme0n1 1   # o el dispositivo que muestre lsblk para /
sudo resize2fs /dev/nvme0n1p1  # o la partición correcta (xvda1, nvme0n1p1, etc.)
df -h /
```

Si `growpart` o `resize2fs` no están, instalar: `sudo apt-get update && sudo apt-get install -y cloud-guest-utils`.

---

## 4. Redeploy de OpenClaw en LAB

En la misma sesión SSM (o en una nueva):

```bash
# Pull, stop/rm anterior, run nuevo (puerto 8081:18789)
docker pull ghcr.io/ccruz0/openclaw:latest
docker stop openclaw || true
docker rm openclaw || true
docker run -d --restart unless-stopped -p 8081:18789 --name openclaw ghcr.io/ccruz0/openclaw:latest

# Verificación
docker logs --tail=80 openclaw
docker port openclaw
```

En el navegador: **https://dashboard.hilovivo.com/openclaw/** — no debe aparecer el placeholder y el WS debe usar `/openclaw/ws`.

---

## 5. Si no puedes ampliar el volumen

- Liberar espacio: `docker system prune -a -f`, limpiar `/var/log` (logrotate o borrar logs viejos), `apt clean`. Con 6.8G puede no ser suficiente para la imagen openclaw.
- La solución fiable es ampliar el EBS (pasos 2 y 3).
