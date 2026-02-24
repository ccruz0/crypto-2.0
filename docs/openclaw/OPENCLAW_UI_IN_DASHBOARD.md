# OpenClaw Web UI in Hilovivo Dashboard

OpenClaw’s native web UI is exposed at **https://dashboard.hilovivo.com/openclaw/** and embedded in the dashboard at **/openclaw** (iframe). No re-skin; the UI is proxied and framed as-is.

**Production:** Basic Auth is **on** by default. Create the htpasswd file before (or immediately after) deploying the config; see §3.

---

## 0. Production hardening checklist (verify after deploy)

| Check | How |
|-------|-----|
| **1) No sensitive API exposed without auth** | From the dashboard server: `curl -I https://dashboard.hilovivo.com/openclaw/` and `curl -I https://dashboard.hilovivo.com/openclaw/api/`. If OpenClaw exposes endpoints like `/execute`, `/run`, `/internal`, `/admin`, they must be protected (Basic Auth is on for the whole `/openclaw/` path). |
| **2) LAB port 8080 not public** | Security Group of the LAB instance: **8080 must not be open to 0.0.0.0/0**. Only the dashboard server IP (or VPC/internal) should be allowed. If 8080 is open to the world, the proxy adds no security. Prefer: LAB in private subnet, dashboard as sole entry. |
| **3) CSP applied to /openclaw/** | In the browser: DevTools → Network → select a request to `/openclaw/` → Response headers. Must include `Content-Security-Policy: frame-ancestors 'self' https://dashboard.hilovivo.com`. No stricter global CSP overriding it. |

---

## 1. Enable / disable the route

- **Enable:** The Nginx location `^~ /openclaw/` is in `nginx/dashboard.conf`. Deploy the config and reload Nginx.
- **Disable:** Remove or comment out the whole `location ^~ /openclaw/ { ... }` block in `nginx/dashboard.conf`, then reload Nginx. The dashboard route `/openclaw` will still exist but the iframe will get 404.

---

## 2. Change LAB host / port

- **File:** `nginx/dashboard.conf`
- **Line:** Inside `location ^~ /openclaw/`, the line:
  ```nginx
  proxy_pass http://52.77.216.100:8080/;
  ```
- **Change:** Replace `52.77.216.100:8080` with your LAB host and port (e.g. `lab.example.com:8080`).
- **Apply:** Reload Nginx: `sudo nginx -t && sudo systemctl reload nginx`.

---

## 3. Basic auth (on by default)

- **Status:** Basic Auth is enabled in `nginx/dashboard.conf` for `/openclaw/`. The agent can create PRs; do not leave it without auth in production.
- **Before first reload:** Create the password file or Nginx will fail to start:
  ```bash
  sudo htpasswd -c /etc/nginx/.htpasswd_openclaw <username>
  ```
  Enter the password when prompted. For additional users: `sudo htpasswd /etc/nginx/.htpasswd_openclaw <other_user>` (no `-c`).
- **Rotate password:** Overwrite the user:
  ```bash
  sudo htpasswd /etc/nginx/.htpasswd_openclaw <username>
  ```
  Then reload Nginx.
- **Disable (not recommended):** Comment out the two `auth_basic` and `auth_basic_user_file` lines and reload Nginx. Only for local/testing.

**Note:** The browser will prompt for credentials when loading `/openclaw/` (or when the iframe loads). The dashboard page at `/openclaw` is not auth’d by Nginx; only the proxied content is. Same-origin iframe usually reuses the same credentials after the first prompt.

---

## 4. IP allowlist (optional)

In `nginx/dashboard.conf`, inside `location ^~ /openclaw/`, an optional block is commented:

```nginx
# satisfy any;
# allow 1.2.3.4;
# allow 10.0.0.0/8;
# deny all;
```

To restrict access by IP: uncomment, set `allow` to your IPs or CIDR, then reload Nginx. With `satisfy any`, either basic auth OR IP allow can satisfy (adjust to `satisfy all` if you want both).

---

## 5. Troubleshooting

| Symptom | What to check |
|--------|----------------|
| **502 Bad Gateway** | LAB host reachable from the Nginx host? `curl -I http://52.77.216.100:8080/` from the Nginx server. OpenClaw UI process listening on 8080 on LAB? |
| **Blank iframe / connection refused** | Same as above; also check that the Nginx server can reach the LAB IP and port (firewall, security groups). |
| **WebSocket fails (UI not updating)** | Nginx must pass `Upgrade` and `Connection` headers; the config does this. If the UI still fails, confirm the OpenClaw app uses a path that goes through `/openclaw/` (e.g. relative URLs). |
| **CSP / X-Frame-Options: iframe blocked** | The proxy removes upstream `X-Frame-Options` and sets `Content-Security-Policy: frame-ancestors 'self' https://dashboard.hilovivo.com` for `/openclaw/` only. If the UI is still blocked, check the response headers with DevTools → Network → select the `/openclaw/` response and verify no other `X-Frame-Options` or stricter `frame-ancestors` is applied. |
| **Timeouts** | Default proxy timeouts for `/openclaw/` are 300s (send/read). For very long operations, increase in the location block: `proxy_send_timeout 600s;` and `proxy_read_timeout 600s;` then reload. |
| **Basic auth prompt in loop** | Ensure the password file exists and is readable by Nginx. If the iframe and parent are same origin, one auth should suffice; clear site data/cache and try again. |

---

## 6. Security

- Basic auth and/or IP allowlist apply only to `/openclaw/`; they are not global.
- Framing is restricted to `https://dashboard.hilovivo.com` via CSP for the proxied response only; global CSP is not weakened.
- No secrets are committed; the password file lives on the server and is not in the repo.
