# OpenClaw Basic Auth password change

Change the nginx Basic Auth password for https://dashboard.hilovivo.com/openclaw/ from your Mac by connecting to PROD.

**Environment:**
- PROD: atp-rebuild-2026, public IP 52.220.32.147
- SSH: `ubuntu@52.220.32.147`, key `~/.ssh/atp-rebuild-2026.pem`
- htpasswd file on server: `/etc/nginx/.htpasswd_openclaw`
- Username in login dialog: **admin**
- Nginx does **not** need a restart after changing htpasswd.

---

## Step 1 — Connect to server

```bash
ssh -i ~/.ssh/atp-rebuild-2026.pem ubuntu@52.220.32.147
```

---

## Step 2 — Update password (on PROD)

If the file already exists:

```bash
sudo htpasswd /etc/nginx/.htpasswd_openclaw admin
```

You will be prompted for the new password (and confirmation). Type it securely.

If the file does **not** exist, create it (use `-c` only the first time):

```bash
sudo htpasswd -c /etc/nginx/.htpasswd_openclaw admin
```

---

## Step 3 — Verify user exists (on PROD)

```bash
sudo cat /etc/nginx/.htpasswd_openclaw
```

Expected format: `admin:$apr1$...` (one line).

---

## Step 4 — Verify OpenClaw endpoint (from Mac or PROD)

```bash
curl -I https://dashboard.hilovivo.com/openclaw/
```

Expected:
- `HTTP/2 401` (or `HTTP/1.1 401`)
- `WWW-Authenticate: Basic realm="OpenClaw"`

---

## Step 5 — Test login in browser

1. Open: https://dashboard.hilovivo.com/openclaw/
2. Username: **admin**
3. Password: the one you just set

---

## Safety

- Do **not** modify any nginx config files.
- Do **not** restart nginx.
- Only update `/etc/nginx/.htpasswd_openclaw`.
