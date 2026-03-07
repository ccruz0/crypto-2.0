# OpenClaw: migrate upstream to private network (VPC internal only)

Mechanical runbook to move the OpenClaw upstream from **public IP** to **private IP** in the same VPC, using SG-to-SG rules. Eliminates 504 timeouts from NAT/EIP/source-IP ambiguity.

---

## 1) Context

**Current:** Dashboard (52.220.32.147) → public internet → OpenClaw public IP (52.77.216.100):8080.

**Target:** Dashboard → VPC private link → OpenClaw private IP:8080.

**Why:** Remove EIP/NAT/source-IP fragility. Reduce attack surface. No need to whitelist dashboard outbound IP in OpenClaw SG.

---

## 2) Preconditions checklist

- [ ] Both EC2 instances exist: **Dashboard** (serves Nginx + frontend) and **OpenClaw** (serves UI on 8080).
- [ ] Both are in the **same VPC** (or document VPC peering if different VPCs).
- [ ] OpenClaw process listens on **0.0.0.0:8080** (not only 127.0.0.1).

**Detect bind:** On OpenClaw host run `sudo ss -lntp | grep ':8080'`. You want `0.0.0.0:8080` or the instance private IP. If only `127.0.0.1:8080`, fix the service bind before migrating (see [OPENCLAW_504_UPSTREAM_DIAGNOSIS.md](OPENCLAW_504_UPSTREAM_DIAGNOSIS.md)).

**Private IP discovery (no console):** If you’re on the OpenClaw host and need the private IP fast:

```bash
hostname -I
curl -s http://169.254.169.254/latest/meta-data/local-ipv4
```

Use the first address from `hostname -I` or the metadata response (usually the same). That’s `<OPENCLAW_PRIVATE_IP>` for the rest of this runbook.

---

## 3) Truth tests (before changing anything)

**From dashboard host (52.220.32.147):**

```bash
# Replace with OpenClaw private IP from EC2 console
ip route get <OPENCLAW_PRIVATE_IP>
```

- Expect: route via a VPC interface (e.g. default via gateway, dev eth0). If "Network is unreachable", instances are not in the same network path.

```bash
curl -sv --max-time 3 http://<OPENCLAW_PRIVATE_IP>:8080/
```

- **Connection timed out** → SG or NACL blocks 8080 from dashboard to OpenClaw (fix in step 4 first).
- **Connection refused** → OpenClaw not listening on 0.0.0.0:8080 or not running.
- **HTTP/1.1 200/302/401** → private path works; safe to switch Nginx.

**On OpenClaw host:**

```bash
sudo ss -lntp | grep ':8080' || true
```

- Must show `0.0.0.0:8080` (or private IP), not only `127.0.0.1:8080`.

```bash
curl -sv --max-time 3 http://127.0.0.1:8080/ || true
```

- Must return HTTP. If not, fix the service before migrating.

---

## 4) AWS Console steps (mechanical)

1. **EC2 → Instances.** Find the **OpenClaw** instance. Note its **Private IPv4** (e.g. 172.31.x.x). You will use this in Nginx.

2. **Security groups**
   - Open the **OpenClaw** instance’s security group (the one attached to that instance).
   - **Inbound → Edit.** Add rule:
     - **Type:** Custom TCP
     - **Port:** 8080
     - **Source:** **Dashboard instance’s security group** (choose by SG ID or name; do not use an IP).
   - Save. Do **not** remove any existing public 8080 rule yet.

3. **(Optional)** If OpenClaw has a public IP, leave it as-is until verification (step 6) passes.

---

## 5) Nginx change (document only)

**Source of truth (edit this file only):**

```bash
sudo nano "$(readlink -f /etc/nginx/sites-enabled/default)"
```

**Where:** Inside the **server 443** block, in `location ^~ /openclaw/`.

**What:** Change only the `proxy_pass` line. From:
```nginx
proxy_pass http://52.77.216.100:8080/;
```
To:
```nginx
proxy_pass http://<OPENCLAW_PRIVATE_IP>:8080/;
```
Replace `<OPENCLAW_PRIVATE_IP>` with the private IP (e.g. from step 4 or from `curl -s http://169.254.169.254/latest/meta-data/local-ipv4` on OpenClaw). Keep all other directives (auth_basic, headers, timeouts) unchanged.

**Reload on dashboard host:**

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 6) Execution checklist (tight)

**On OpenClaw host**

- Confirm it listens on the VPC interface, not only loopback:

```bash
sudo ss -lntp | grep ':8080' || true
```

- **Good:** `0.0.0.0:8080` or `172.31.x.x:8080`
- **Not good:** `127.0.0.1:8080` only → fix bind before continuing.

**On AWS**

- OpenClaw SG → Inbound: add **TCP 8080**, Source: **Dashboard SG** (not an IP).
- Keep existing public 8080 rule for now.

**On dashboard host**

- Test private reachability **before** touching Nginx:

```bash
curl -sv --max-time 3 http://<OPENCLAW_PRIVATE_IP>:8080/
```

- **Expected:** Any HTTP response (200/301/302/401). Not a timeout. If timeout, fix SG/NACL first.

**Nginx change (dashboard host)**

- Edit: `sudo nano "$(readlink -f /etc/nginx/sites-enabled/default)"`
- In server 443, inside `location ^~ /openclaw/`, change only `proxy_pass` to `http://<OPENCLAW_PRIVATE_IP>:8080/;`
- Reload: `sudo nginx -t && sudo systemctl reload nginx`

**No-downtime guarantee:** Before changing Nginx, run `curl -I https://dashboard.hilovivo.com/openclaw/`. After changing and reloading, run it again. If both return **401** (not 504), users will not experience downtime. That’s your safe signal at 2am.

**Verification**

```bash
curl -I https://dashboard.hilovivo.com/openclaw/
```

- **Expected:** 401 (from Nginx). Then in browser: auth and OpenClaw UI loads (no 504).

**Lock it down**

- Remove OpenClaw SG inbound **TCP 8080 from 0.0.0.0/0**.
- Optional: remove public IPv4 from OpenClaw instance (or move to private subnet).

**Paste these two outputs to confirm you’re ready for the Nginx switch:**

- From dashboard: `curl -sv --max-time 3 http://<OPENCLAW_PRIVATE_IP>:8080/`
- From OpenClaw: `sudo ss -lntp | grep ':8080' || true`

With those, we can say if it’s safe to change Nginx.

---

## 7) Verification checklist (detailed)

**From dashboard host:**

```bash
curl -I https://dashboard.hilovivo.com/openclaw/
```

- Expect: **401 Unauthorized**. If 504, private path or SG is wrong; fix before removing public access.

**In browser:** Open https://dashboard.hilovivo.com/openclaw/, authenticate. Confirm OpenClaw UI loads (no 504).

**From dashboard host (direct to private IP):**

```bash
curl -sv --max-time 3 http://<OPENCLAW_PRIVATE_IP>:8080/
```

- Expect: HTTP response (200/302/401). If timeout or refused, do not remove public rule yet.

---

## 8) Remove public exposure (only after verification passes)

1. **OpenClaw SG → Inbound.** Remove the rule that allows **TCP 8080** from **0.0.0.0/0** (or from a specific public IP). Keep the rule that allows 8080 from the **Dashboard SG**.

2. **(Optional)** Remove public IPv4 from the OpenClaw instance, or move the instance to a private-only subnet. Only if your ops allow it.

3. **Confirm no public reachability:** From a machine **outside** the VPC (e.g. your laptop), run:
   ```bash
   curl -sv --max-time 5 http://52.77.216.100:8080/
   ```
   Expect: **Connection timed out** or **Connection refused**. If you get HTTP, the public rule is still active or another path exists.

---

## 9) Rollback plan

If something breaks after switching to private IP:

1. **Dashboard host:** Edit Nginx again. Change `proxy_pass` back to:
   ```nginx
   proxy_pass http://52.77.216.100:8080/;
   ```
2. **Dashboard host:** `sudo nginx -t && sudo systemctl reload nginx`
3. **OpenClaw SG:** Re-add inbound TCP 8080 from the dashboard public IP (or 0.0.0.0/0 temporarily) if you had removed it.

After rollback, fix the private path (SG, NACL, bind) and retry the migration when ready.

---

## 10) Decision table

| Symptom | Likely cause | Next action |
|--------|--------------|-------------|
| Timeout to private IP from dashboard | SG/NACL blocks 8080 from dashboard to OpenClaw | Add inbound 8080 from **Dashboard SG** on OpenClaw SG; check NACL allow 8080 and ephemeral return |
| Refused to private IP from dashboard | OpenClaw not listening on 0.0.0.0:8080 or process down | On OpenClaw host: `ss -lntp | grep 8080` and fix bind or restart service |
| Works local (127.0.0.1) only on OpenClaw | Service bound to 127.0.0.1 only | Change app/config to listen on 0.0.0.0:8080 |
| 401 OK but UI blank in browser | Auth/iframe issue, not network | See [OPENCLAW_IFRAME_BLANK_DIAGNOSIS.md](OPENCLAW_IFRAME_BLANK_DIAGNOSIS.md) |

---

**File:** `docs/openclaw/OPENCLAW_PRIVATE_NETWORK_MIGRATION.md`
