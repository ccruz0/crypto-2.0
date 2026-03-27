# Cursor → SSH → AWS: ejecutar código en EC2

Este documento describe **cómo Cursor (o cualquier terminal en tu Mac) puede conectarse por SSH a la instancia EC2** para ejecutar comandos en el servidor sin salir del IDE.

---

## Idea general

- **Cursor usa la terminal de tu máquina local** (tu Mac). No tiene su propia sesión SSH.
- Cuando en Cursor ejecutas un comando, **corre en tu Mac** con tu usuario, tu `PATH` y tu **configuración SSH** (`~/.ssh/config`, claves en `~/.ssh/`).
- Para “ejecutar código en AWS” desde Cursor, lo que haces es **lanzar `ssh <host> 'comando'`** desde esa terminal. El host debe estar definido en `~/.ssh/config` con la **clave correcta** para la instancia EC2.

Si la clave no está bien configurada, verás `Permission denied (publickey)` aunque la IP sea correcta.

---

## Requisitos en tu Mac

1. **Clave privada** (.pem o id_rsa) que la instancia EC2 tenga en `~/.ssh/authorized_keys` del usuario `ubuntu`.
2. **Entrada en `~/.ssh/config`** que asocie un nombre de host (alias) a la IP de la instancia y a esa clave.

### Ejemplo de configuración que funciona (PROD actual)

Para la instancia **atp-rebuild-2026** (IP 52.220.32.147), en tu Mac deberías tener algo así en `~/.ssh/config`:

```
Host dashboard-prod
  HostName 52.220.32.147
  User ubuntu
  IdentityFile ~/.ssh/atp-rebuild-2026.pem
  IdentitiesOnly yes
  ConnectTimeout 15
  StrictHostKeyChecking accept-new
  ServerAliveInterval 10
  ServerAliveCountMax 3
```

- **Host** = alias que usarás: `ssh dashboard-prod`.
- **HostName** = IP pública (o DNS) de la instancia. Debe coincidir con la instancia actual (ver AWS Console o `docs/aws/AWS_PROD_QUICK_REFERENCE.md`).
- **User** = normalmente `ubuntu` en AMIs Ubuntu.
- **IdentityFile** = ruta al `.pem` (o clave privada) que se usó al crear la instancia o que añadiste a `authorized_keys`.

Si usas `ssh ubuntu@52.220.32.147` **sin** este bloque, SSH puede estar usando otra clave por defecto (p. ej. `~/.ssh/id_rsa`) que la instancia no tiene → **Permission denied (publickey)**.

---

## Cómo ejecutar comandos en AWS desde Cursor

### Opción 1: Comando único (sin abrir sesión interactiva)

En la terminal de Cursor (en tu Mac):

```bash
ssh dashboard-prod 'cd /home/ubuntu/crypto-2.0 && docker compose --profile aws ps'
```

Todo lo que va entre comillas simples se ejecuta **en la instancia EC2**. Puedes encadenar varios comandos con `&&`.

### Opción 2: Varios comandos (una sola conexión)

```bash
ssh dashboard-prod 'cd /home/ubuntu/crypto-2.0 && \
  sudo chown ubuntu:ubuntu secrets/runtime.env && \
  chmod 600 secrets/runtime.env && \
  docker compose --profile aws up -d'
```

### Opción 3: Sesión interactiva

```bash
ssh dashboard-prod
```

Entras en la instancia; el prompt pasará a algo como `ubuntu@ip-172-31-32-169:~$`. Ahí ejecutas lo que quieras (por ejemplo los comandos del bloque anterior sin el prefijo `ssh dashboard-prod '...'`). Sales con `exit`.

---

## Qué host usar

| Entorno | Alias recomendado | IP (referencia) | Comentario |
|--------|--------------------|------------------|------------|
| PROD (atp-rebuild-2026) | `dashboard-prod` | 52.220.32.147 | Definir en `~/.ssh/config` con `IdentityFile ~/.ssh/atp-rebuild-2026.pem`. |
| Alias antiguo | `hilovivo-aws` | 47.130.143.159 | IP antigua; si la instancia se recreó, actualizar HostName a 52.220.32.147 o usar `dashboard-prod`. |

Comprueba en AWS Console → EC2 → tu instancia la **Public IPv4** (o Elastic IP) y que coincida con el `HostName` del alias que uses.

---

## Si Cursor “no puede” ejecutar en AWS

- **Permission denied (publickey)**  
  La instancia no acepta la clave que está usando SSH. Solución: usar un host de `~/.ssh/config` que tenga `IdentityFile` apuntando al `.pem` correcto (p. ej. `ssh dashboard-prod` en lugar de `ssh ubuntu@52.220.32.147`). Ver también `docs/runbooks/EC2_SSH_TIMEOUT_DEBUG.md`.

- **Connection timed out**  
  Red: Security Group (puerto 22 solo desde tu IP), IP incorrecta o instancia apagada. Ver `docs/runbooks/EC2_SSH_TIMEOUT_DEBUG.md`.

- **Cursor no tiene “acceso directo” a EC2**  
  Cursor no mantiene una sesión SSH propia. Siempre ejecuta comandos en la terminal de tu Mac; si en esa terminal `ssh dashboard-prod '...'` funciona, desde Cursor también (misma shell, mismo `~/.ssh/config` y mismas claves).

---

## Alternativa: SSM (sin SSH)

Si no quieres abrir el puerto 22 o la instancia no es accesible por SSH, puedes usar **AWS Systems Manager (SSM)** desde tu Mac (con AWS CLI configurado):

```bash
./scripts/aws/fix_runtime_env_and_up_ssm.sh
```

Ese script comprueba si la instancia está **Online** en SSM; si lo está, envía los comandos (chown, chmod, docker compose up) a la instancia. Si el estado es **ConnectionLost**, el script no puede ejecutar nada y tendrás que usar SSH (o EC2 Instance Connect desde la consola AWS). Referencia de instancias: `docs/aws/AWS_PROD_QUICK_REFERENCE.md`.

---

## Resumen

| Objetivo | Comando / acción |
|----------|------------------|
| Conectar por SSH desde Cursor/Mac | `ssh dashboard-prod` (con `dashboard-prod` en `~/.ssh/config` y clave `.pem`). |
| Ejecutar un comando en EC2 desde Cursor | `ssh dashboard-prod 'cd /home/ubuntu/crypto-2.0 && <comando>'` |
| Evitar Permission denied | Usar el alias que tenga `IdentityFile` correcto (p. ej. `dashboard-prod`), no solo `ssh ubuntu@IP`. |
| Ejecutar sin SSH (si SSM está Online) | `./scripts/aws/fix_runtime_env_and_up_ssm.sh` (u otros scripts que usen `aws ssm send-command`). |
