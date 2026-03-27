# OpenClaw LAB — Instalar desde Mac

Instancia LAB: **i-0d82c172235770a0d** (ap-southeast-1).

**Flujo recomendado (seguro):** PAT solo en LAB vía SSH, sin SSM. Ver **[RUNBOOK_SECURE_INSTALL.md](RUNBOOK_SECURE_INSTALL.md)** y ejecutar `./scripts/openclaw/prompt_pat_and_install.sh` (comprueba egress, pop-up para PAT, escritura directa en LAB por SSH).

---

## 1. Comprobar egress (HTTPS)

La instancia LAB debe poder salir por **puerto 443** a internet (GitHub, mirrors Ubuntu). Si no, `apt update` y `git clone` / `curl` fallan.

- **Security group** de la instancia: regla de salida (egress) **TCP 443** a `0.0.0.0/0` (o al menos a GitHub y a los mirrors).
- Si solo tienes 443 a metadata: en la instancia hay que pasar apt a HTTPS; ver [RUNBOOK_EGRESS_OPTION_A1.md](../audit/RUNBOOK_EGRESS_OPTION_A1.md) §3.1.

Comprobar desde la instancia (SSM):

```bash
aws ssm start-session --target i-0d82c172235770a0d --region ap-southeast-1
# Dentro:
curl -sI --connect-timeout 5 https://github.com | head -1
# Debe devolver "HTTP/2 200" o similar. Si timeout → revisar egress/NAT.
```

---

## 2. Un comando: pop-up para la PAT y disparar instalación

En tu Mac, desde la raíz del repo:

```bash
./scripts/openclaw/prompt_pat_and_install.sh
```

- Se abre una **ventana** para pegar tu **GitHub fine-grained PAT** (Contents R/W, Pull requests R/W, Metadata R).
- El script guarda la PAT en SSM (SecureString) y lanza la instalación completa en LAB vía `send-command`.
- No hace falta conectar por SSM a mano ni poner la PAT en ningún archivo.

Alternativa sin pop-up (PAT por variable o archivo):

```bash
OPENCLAW_PAT=ghp_xxx ./scripts/openclaw/store_pat_and_install.sh
# o: echo ghp_xxx > .openclaw_pat && ./scripts/openclaw/store_pat_and_install.sh
```

---

## 3. Verificar instalación

- El script imprime un **CommandId** y espera ~60 s; luego muestra salida/error del comando en LAB.
- En LAB (SSM):

  ```bash
  docker ps -f name=openclaw
  cd /home/ubuntu/crypto-2.0 && docker compose -f docker-compose.openclaw.yml logs -f openclaw
  ```

- Siguiente: [INSTALL_CONTINUE.md](INSTALL_CONTINUE.md) — "After installation" y [LAB_SETUP_AND_VALIDATION.md](LAB_SETUP_AND_VALIDATION.md).

---

## Si la instancia no tiene salida HTTPS

Hasta que egress permita 443 a internet, la instalación remota (curl/git en LAB) no funcionará. Opciones:

1. Ajustar security group / NAT para que LAB tenga salida 443.
2. Conectar por SSM y seguir los pasos manuales de [INSTALL_CONTINUE.md](INSTALL_CONTINUE.md) (apt HTTPS, docker, clone, token, .env.lab, compose).

Referencia egress: [EGRESS_HARDENING_DESIGN.md](../audit/EGRESS_HARDENING_DESIGN.md), [RUNBOOK_EGRESS_OPTION_A1.md](../audit/RUNBOOK_EGRESS_OPTION_A1.md).
