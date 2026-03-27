# Fix 504 on /openclaw/ — pasos concretos

**Estado comprobado (SSM en LAB):**

- **IP privada de OpenClaw (LAB):** `172.31.3.214`
- **Puerto 8080 en LAB:** nada escuchando → **OpenClaw no está corriendo**
- **Dashboard:** SSM ConnectionLost → hay que usar **EC2 Instance Connect** al Dashboard (52.220.32.147)

---

## 1) En el host **OpenClaw (LAB)** — levantar OpenClaw

Conéctate al LAB (Session Manager o EC2 Instance Connect): **atp-lab-ssm-clean** (i-0d82c172235770a0d).

Si el repo **no** está clonado:

```bash
sudo -u ubuntu git clone https://github.com/ccruz0/crypto-2.0.git /home/ubuntu/crypto-2.0
# o la URL de tu repo
cd /home/ubuntu/crypto-2.0
```

Si ya existe el repo:

```bash
cd /home/ubuntu/crypto-2.0   # o donde esté el clone
git pull origin main
```

Levantar OpenClaw:

```bash
docker compose -f docker-compose.openclaw.yml up -d
sudo ss -lntp | grep ':8080'
```

Debe aparecer `0.0.0.0:8080`. Si no, revisar [OPENCLAW_504_UPSTREAM_DIAGNOSIS.md](OPENCLAW_504_UPSTREAM_DIAGNOSIS.md).

---

## 2) En el host **Dashboard** — Nginx con IP privada

Conéctate al **Dashboard** por **EC2 Instance Connect**: atp-rebuild-2026 (52.220.32.147).

```bash
cd ~/crypto-2.0 || cd /home/ubuntu/crypto-2.0
git pull origin main
sudo ./scripts/openclaw/insert_nginx_openclaw_block.sh 172.31.3.214
```

Comprobar:

```bash
curl -I https://dashboard.hilovivo.com/openclaw     # → 301
curl -I https://dashboard.hilovivo.com/openclaw/    # → 401 (o 200 si ya autenticado)
```

Si sigues viendo **504**: desde el Dashboard prueba `curl -sv --max-time 5 http://172.31.3.214:8080/`. Si hace timeout → **Security Group**: en la instancia LAB, Inbound, añadir regla **Custom TCP 8080**, origen = **Security Group del Dashboard**.

---

## 3) Navegador

Abre **https://dashboard.hilovivo.com/openclaw**. Debería pedir usuario/contraseña (Basic Auth). Usa el usuario/contraseña del archivo `/etc/nginx/.htpasswd_openclaw` del Dashboard (creado con `sudo htpasswd -c /etc/nginx/.htpasswd_openclaw openclaw`).
