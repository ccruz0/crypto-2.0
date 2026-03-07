# Crypto Instance → PROD Hardening Runbook

**Goal:** Harden the existing "Crypto" EC2 instance as PROD, then create a new clean EC2 as LAB.  
**Prerequisite:** EBS snapshot of Crypto volumes (rollback in one click).  
**Ref:** [EC2_CRYPTO_PROD_VIABILITY_AUDIT.md](./EC2_CRYPTO_PROD_VIABILITY_AUDIT.md)

---

## Order of operations

### 1) Snapshot first (no changes until done)

- **Where:** AWS Console → EC2 → Volumes (or Instance → Storage) → Create snapshot.
- Create an EBS snapshot of all volumes attached to the Crypto instance.
- Do not make any other changes until the snapshot exists.

---

### 2) Confirm what is exposed on the live box

On the Crypto instance:

```bash
cd ~
sudo ss -lntp | grep -E '(:80|:443|:3000|:8002|:5432|:9000)\b'
```

**Target state:**

| Port  | Expectation |
|-------|-------------|
| 80    | Open (nginx) |
| 443   | Open (nginx) |
| 3000  | **Only** `127.0.0.1:3000` |
| 8002  | **Only** `127.0.0.1:8002` |
| 5432  | **Not** listening on host (DB internal only) |
| 9000  | Identify; then either 127.0.0.1 only or behind nginx / removed |

---

### 3) Identify port 9000

```bash
cd ~
sudo lsof -iTCP:9000 -sTCP:LISTEN -n -P
```

- If it’s a service you don’t need → stop it.
- If you need it → ensure it is bound to `127.0.0.1` only or protected behind nginx (not public).

---

### 4) Find and remove env backups on the server

**Find candidates:**

```bash
cd ~
sudo find / -maxdepth 4 -type f \( -name "*.env*" -o -name ".env*" -o -name "*.bak*" -o -name "*secret*" -o -name "*key*" \) 2>/dev/null | head -n 200
```

**Specifically .env.aws backups:**

```bash
cd ~
sudo find / -maxdepth 6 -type f -name ".env.aws*" 2>/dev/null
```

**Before deleting:** Inspect (replace path with actual path):

```bash
sudo sed -n '1,120p' /path/to/file
```

**Then remove:**

```bash
sudo rm -f /path/to/file
```

---

### 5) Rotate secrets if .env.aws ever had real values committed

- Rotate in each system: Crypto.com Exchange, Telegram, OpenAI, SECRET_KEY, ADMIN_ACTIONS_KEY, DIAGNOSTICS_API_KEY, etc.
- Update server env (e.g. `.env.aws`, `secrets/runtime.env`) with the new values.
- If real secrets were committed, treat them as burned; rotation is mandatory. History rewrite is optional.

---

### 6) Redeploy from the cleaned repo

- Pull latest (e.g. `git fetch && git reset --hard origin/main` in repo).
- Render runtime env: `bash scripts/aws/render_runtime_env.sh`
- Deploy: e.g. `bash scripts/deploy_aws.sh` or your CI pipeline.
- Verify: `curl -sS http://localhost:8002/api/health/system | jq` and HTTPS in browser.

---

## Paste command output here (for exact hardening guidance)

After running the two commands on Crypto, paste the output below. Use it to decide what is exposed, what to shut down or rebind, and whether Crypto is safe to label PROD.

### 2) Listening ports (80, 443, 3000, 8002, 5432, 9000)

```bash
sudo ss -lntp | grep -E '(:80|:443|:3000|:8002|:5432|:9000)\b'
```

**Output:**

```
(paste here)
```

---

### 3) Process on port 9000

```bash
sudo lsof -iTCP:9000 -sTCP:LISTEN -n -P
```

**Output:**

```
(paste here)
```

---

## After Crypto is PROD: create LAB clean

LAB rules:

- No public inbound (no 0.0.0.0/0 on 80/443 or app ports).
- SSM only for access (Session Manager, or SSH via SSM port forwarding).
- No production secrets; use separate Telegram bot/channel and API keys for LAB.

---

## LAB placement: same VPC vs separate

| Option | Pros | Cons |
|--------|------|------|
| **Same VPC** | One VPC to manage; LAB can use private DNS/VPC endpoints if you add them; lower cost (no extra NAT/VPC). | Misconfiguration (e.g. security group) could expose LAB to PROD network; shared blast radius. |
| **Separate VPC** | Strong isolation; LAB experiments cannot touch PROD network; clear boundary. | Extra VPC and possibly NAT; more networking to maintain. |

**Recommendation:** **Same VPC, different subnets and security groups.**  
- Put LAB in its own subnet and give it a security group with **no** inbound from 0.0.0.0/0 (only SSM / your bastion or VPN).  
- PROD keeps 80/443 open; LAB has no public IP or no 0.0.0.0 rules.  
- Use separate IAM/instance profiles and env (no prod secrets). That gives you isolation without a second VPC. Choose a **separate VPC** only if you need strict compliance or want zero chance of cross-VPC mistakes.
