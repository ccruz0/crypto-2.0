# Architecture v1.1 — Acceptance checklist (production locked)

Use this after migration or after any change to Dashboard/OpenClaw networking. **Done = all checks pass.**

Reference: [ARCHITECTURE_V1_1_INTERNAL_SERVICE.md](ARCHITECTURE_V1_1_INTERNAL_SERVICE.md)

---

- [ ] **1. OpenClaw not exposed to internet**  
  OpenClaw SG has **no** inbound TCP 8080 from 0.0.0.0/0. Only from Dashboard SG.

- [ ] **2. Dashboard → OpenClaw over private IP**  
  Nginx `proxy_pass` in server 443 uses OpenClaw **private IP** (e.g. 172.31.x.x), not public.

- [ ] **3. OpenClaw locations in server 443**  
  `sudo nginx -T` shows `location = /openclaw` and `location ^~ /openclaw/` inside the **443** server block, **before** `location /`.

- [ ] **4. Edit path is canonical**  
  Nginx config is edited via `sudo nano "$(readlink -f /etc/nginx/sites-enabled/default)"` (no stray backups in sites-enabled).

- [ ] **5. Public 401**  
  `curl -I https://dashboard.hilovivo.com/openclaw/` returns **401** (not 504, not 404).  
  *If 504:* [OPENCLAW_504_UPSTREAM_DIAGNOSIS.md](OPENCLAW_504_UPSTREAM_DIAGNOSIS.md) — run the 3 commands, paste the 3 outputs → one change.

- [ ] **6. Browser flow**  
  In browser: open `/openclaw/`, Basic Auth prompt, then OpenClaw UI loads (no blank, no 504).

- [ ] **7. Private reachability from dashboard**  
  From dashboard host: `curl -sv --max-time 3 http://<OPENCLAW_PRIVATE_IP>:8080/` returns HTTP (200/302/401).  
  *If timeout/refused:* same runbook as check 5 (invariant #2 or #3).

- [ ] **8. OpenClaw listen bind**  
  On OpenClaw host: `sudo ss -lntp | grep ':8080'` shows **0.0.0.0:8080** (or private IP), not only 127.0.0.1.

- [ ] **9. SG-to-SG rule**  
  OpenClaw SG inbound TCP 8080 has **Source = Dashboard SG** (by SG ID/name).

- [ ] **10. No public 8080 from outside**  
  From a machine outside the VPC: `curl -sv --max-time 5 http://<OPENCLAW_PUBLIC_IP>:8080/` times out or is refused (no HTTP).

---

**Sign-off:** When all 10 are checked, production is locked to the internal service model. Do not re-open OpenClaw:8080 to the internet without a formal change.
