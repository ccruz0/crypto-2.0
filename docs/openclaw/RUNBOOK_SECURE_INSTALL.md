# OpenClaw LAB — Instalación segura (sin SSM para la PAT)

Instancia LAB: **i-0d82c172235770a0d**. La PAT **nunca** se guarda en SSM; solo vive en el host LAB en `~/secrets/openclaw_token` (modo 600). No se imprime ni se expone por variable de entorno en el contenedor.

---

## 1. Requisitos

- Acceso **SSH** a la instancia LAB (clave y host, o resolución desde `LAB_INSTANCE_ID`).
- Egress **HTTPS (443)** desde LAB a GitHub y a mirrors de Ubuntu (para apt/git).

---

## 2. Comprobar egress (antes de instalar)

En LAB (vía SSH):

```bash
curl -sI --connect-timeout 10 https://github.com
curl -sI --connect-timeout 10 https://api.github.com
```

Si hay **timeout**:

- Mensaje claro: *"LAB instance has no HTTPS egress (port 443). Fix Security Group or NAT before continuing."*
- No continuar hasta corregir el security group o NAT.

---

## 3. Transferir la PAT solo por SSH (almacenamiento local en LAB)

Desde tu Mac (en la raíz del repo):

```bash
./scripts/openclaw/prompt_pat_and_install.sh
```

El script:

1. Comprueba egress en LAB (curl a github.com y api.github.com).
2. Pide la PAT (ventana en macOS o `read -s` en terminal); **nunca** la escribe en logs.
3. Crea en LAB vía SSH:
   - `~/secrets` (chmod 700)
   - `~/secrets/openclaw_token` (chmod 600) y escribe la PAT por stdin.
4. Deja de usar la variable local de la PAT de inmediato.
5. **No** usa `aws ssm put-parameter` ni `send-command` con el token.

Variables opcionales:

- `LAB_SSH_HOST` — IP o hostname de LAB (si no se resuelve por `LAB_INSTANCE_ID`).
- `LAB_SSH_KEY` — Ruta a la clave SSH (p. ej. `~/.ssh/atp-lab.pem`).
- `LAB_SSH_USER` — Usuario SSH (por defecto `ubuntu`).

---

## 4. Verificación del token en LAB

En LAB (SSH):

```bash
ls -la ~/secrets
stat ~/secrets/openclaw_token
```

Comprobar:

- `~/secrets` existe y es modo **700**.
- `~/secrets/openclaw_token` existe, es **600** y el propietario es el usuario correcto.
- El archivo **no** es world-readable.

---

## 5. Arrancar OpenClaw (Docker)

En LAB, **antes** de levantar Docker, confirmar que el usuario tiene UID 1000 (el contenedor corre como `user: "1000:1000"` y debe poder leer el token):

```bash
id
# Debe mostrar uid=1000(ubuntu) (o similar). Si no es 1000, el contenedor no podrá leer ~/secrets/openclaw_token.
```

Luego:

```bash
cd /home/ubuntu/crypto-2.0
cp -n .env.lab.example .env.lab
# Ajustar .env.lab: GIT_REPO_URL, OPENCLAW_IMAGE
docker compose -f docker-compose.openclaw.yml up -d
docker compose -f docker-compose.openclaw.yml ps
```

El token se monta **solo** como archivo de solo lectura; no hay variable de entorno con el valor del token.

---

## 6. Servicio (opcional)

```bash
sudo cp /home/ubuntu/crypto-2.0/scripts/openclaw/openclaw.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable openclaw
sudo systemctl start openclaw
```

---

## 7. Checklist de seguridad

- [ ] PAT **no** está en SSM Parameter Store.
- [ ] PAT **no** se imprime ni se registra en logs.
- [ ] En LAB, `~/secrets` es 700 y `~/secrets/openclaw_token` es 600.
- [ ] Contenedor: `user` no-root, `read_only: true`, `cap_drop: ALL`, `no-new-privileges:true`.
- [ ] Token montado como **read-only** (`:ro`); no se pasa por env.
- [ ] No se monta el socket de Docker en el contenedor.
- [ ] Límites de recursos (mem/cpu) definidos en el compose.
- [ ] Producción **no** se modifica; solo LAB.

---

## Referencias

- [AUDIT_TOKEN_CONSUMPTION.md](AUDIT_TOKEN_CONSUMPTION.md) — Auditoría de cómo se consume el token (este repo + contenedor).
- [RUNBOOK_OPENCLAW_LAB.md](RUNBOOK_OPENCLAW_LAB.md) — Pasos manuales en LAB.
- [FINAL_SECURITY_CHECKLIST.md](FINAL_SECURITY_CHECKLIST.md) — Checklist ampliado.
- [RUNBOOK_INSTALAR_DESDE_MAC.md](RUNBOOK_INSTALAR_DESDE_MAC.md) — Flujo anterior (referencia; el flujo seguro es este runbook).
