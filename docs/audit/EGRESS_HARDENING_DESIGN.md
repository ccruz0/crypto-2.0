# Egress Hardening Design — ATP Production EC2

**Context:** Production EC2 runs Docker-based automated trading platform. SSH disabled; access only via SSM + IAM. This document lists all external dependencies found in the repository and proposes outbound (egress) restriction options.

**Scope:** Application and observability stack only. No application code changes. No assumptions about services not present in the repo.

---

## 1. EXTERNAL_DEPENDENCIES (from repository analysis)

All outbound destinations used by backend, market-updater, observability, and host/container needs:

| # | Service name | Protocol | Port | Destination | Used by | IP restriction feasible? |
|---|--------------|----------|------|-------------|---------|---------------------------|
| 1 | Crypto.com Exchange REST | HTTPS | 443 | `api.crypto.com` | backend, market-updater (orders, account, tickers, candlestick) | No (use domain; CDN IPs vary) |
| 2 | Crypto.com Exchange WebSocket | WSS | 443 | `stream.crypto.com` | backend (optional, `USE_WEBSOCKET=true`) | No |
| 3 | Crypto.com public (VPN gate / ticker) | HTTPS | 443 | `api.crypto.com` (v2 public) | vpn_gate, scripts | No |
| 4 | Telegram Bot API | HTTPS | 443 | `api.telegram.org` | backend (telegram_notifier, telegram_commands), telegram-alerts container | No |
| 5 | Outbound IP check (diagnostics) | HTTPS | 443 | `api.ipify.org` | routes_internal, routes_diag, scripts (Crypto.com IP whitelist check) | No |
| 6 | Outbound IP check (alt) | HTTPS | 443 | `icanhazip.com`, `ifconfig.me` | scripts (diagnose_exchange_auth, etc.) | No |
| 7 | AWS instance metadata | HTTP | 80 | `169.254.169.254` | crypto_com_guardrail (EC2 detection) | N/A (link-local) |
| 8 | Binance (market data fallback) | HTTPS | 443 | `api.binance.com` | market_updater (OHLCV when Crypto.com insufficient), price_fetcher, robust_price_fetcher | No |
| 9 | Kraken (market data) | HTTPS | 443 | `api.kraken.com` | price_fetcher | No |
| 10 | CoinPaprika (market data) | HTTPS | 443 | `api.coinpaprika.com` | price_fetcher, robust_price_fetcher | No |
| 11 | CoinGecko (market data) | HTTPS | 443 | `api.coingecko.com` | robust_price_fetcher; already in egress_guard | No |
| 12 | GitHub API (optional) | HTTPS | 443 | `api.github.com` | routes_monitoring (workflow dispatch when GITHUB_TOKEN set) | No |
| 13 | SSM / Session Manager | HTTPS | 443 | `*.ssm.<region>.amazonaws.com`, `*.ec2messages.<region>.amazonaws.com`, `*.ssmmessages.<region>.amazonaws.com` | EC2 host (SSM Agent) | Yes (AWS IP ranges or prefix lists) |
| 14 | Docker image registry | HTTPS | 443 | `registry-1.docker.io`, or `*.ecr.<region>.amazonaws.com` if using ECR | Host (docker pull) | Prefer domain; ECR can use VPC endpoint |
| 15 | DNS | UDP/TCP | 53 | VPC DNS (e.g. `169.254.169.253`) or resolver | Host + containers | N/A (VPC) or allow resolver IPs |
| 16 | NTP (optional) | UDP | 123 | e.g. `169.254.169.123` (AWS time sync) or pool | Host | Optional |

**References in code:**

- **Crypto.com:** `backend/app/services/brokers/crypto_com_constants.py` (REST_BASE, WS_USER, WS_MARKET), `docker-compose.yml` (EXCHANGE_CUSTOM_BASE_URL, VPN_GATE_URL), `backend/app/utils/vpn_gate.py`, `backend/market_updater.py`, `backend/price_fetcher.py`, `backend/robust_price_fetcher.py`, multiple scripts.
- **Telegram:** `backend/app/services/telegram_notifier.py`, `backend/app/services/telegram_commands.py`, `scripts/aws/observability/telegram-alerts/server.py`.
- **IP check:** `backend/app/api/routes_internal.py`, `backend/app/api/routes_diag.py`, `backend/app/services/brokers/crypto_com_trade.py`, scripts (ipify, icanhazip, ifconfig.me).
- **AWS metadata:** `backend/app/core/crypto_com_guardrail.py`.
- **Binance/Kraken/CoinPaprika/CoinGecko:** `backend/market_updater.py`, `backend/price_fetcher.py`, `backend/robust_price_fetcher.py`, `backend/app/services/data_sources.py`.
- **GitHub:** `backend/app/api/routes_monitoring.py` (GITHUB_TOKEN, workflow dispatch).

---

## 2. OPTION A — Minimal secure egress (Security Group only)

**Idea:** Replace default “all outbound 0.0.0.0/0” with explicit outbound rules by destination and port. No VPC endpoints, no NACL changes.

### 2.1 Outbound rules (Security Group)

| Type | Protocol | Port | Destination | Purpose |
|------|----------|------|-------------|---------|
| HTTPS | TCP | 443 | `api.crypto.com` | Crypto.com REST + v2 public |
| HTTPS | TCP | 443 | `stream.crypto.com` | Crypto.com WebSocket (if used) |
| HTTPS | TCP | 443 | `api.telegram.org` | Telegram Bot API |
| HTTPS | TCP | 443 | `api.ipify.org` | Outbound IP diagnostics |
| HTTPS | TCP | 443 | `icanhazip.com` | Outbound IP (scripts) |
| HTTPS | TCP | 443 | `ifconfig.me` | Outbound IP (scripts) |
| HTTPS | TCP | 443 | `api.binance.com` | Market data fallback |
| HTTPS | TCP | 443 | `api.kraken.com` | Market data |
| HTTPS | TCP | 443 | `api.coinpaprika.com` | Market data |
| HTTPS | TCP | 443 | `api.coingecko.com` | Market data |
| HTTPS | TCP | 443 | `api.github.com` | Optional workflow dispatch |
| HTTPS | TCP | 443 | `*.ssm.<region>.amazonaws.com` | SSM (Session Manager) |
| HTTPS | TCP | 443 | `*.ec2messages.<region>.amazonaws.com` | SSM |
| HTTPS | TCP | 443 | `*.ssmmessages.<region>.amazonaws.com` | SSM |
| HTTPS | TCP | 443 | `registry-1.docker.io` | Docker Hub (if used) |
| HTTPS | TCP | 443 | `*.ecr.<region>.amazonaws.com` | ECR (if used) |
| HTTP | TCP | 80 | `169.254.169.254/32` | AWS instance metadata |
| All traffic | TCP | 53 | `0.0.0.0/0` (or VPC DNS) | DNS over TCP (fallback) |
| All traffic | UDP | 53 | `0.0.0.0/0` (or VPC DNS) | DNS |

**Important:** AWS Security Groups do **not** support FQDN in rules; they support **CIDR only**. So you cannot literally put `api.crypto.com` in the SG. You have two practical approaches:

- **A1 — Allow HTTPS 443 to 0.0.0.0/0**  
  - Single rule: Outbound TCP 443 to 0.0.0.0/0.  
  - Restrict “what” at application layer (egress_guard + allowlisted domains).  
  - Pros: No breakage when third-party IPs change.  
  - Cons: Any compromised process can try any HTTPS endpoint (still limited by app allowlist if all clients use http_client).

- **A2 — Use AWS prefix lists / resolved IPs for known services**  
  - Maintain prefix lists or IP ranges for API providers (e.g. from provider docs or resolve and update periodically).  
  - Pros: Restricts at network layer.  
  - Cons: Many providers use CDNs; IPs change; maintenance and risk of over-restricting (e.g. Crypto.com, Telegram).

**Recommendation for Option A:** Use **A1** (outbound TCP 443 to 0.0.0.0/0) and keep application-layer egress_guard as the main control. Optionally restrict other ports (e.g. block TCP 80 except to 169.254.169.254, allow DNS 53, allow SSM-related IP ranges if you use prefix lists).

### 2.2 Exact steps (Option A — A1 style)

1. **EC2 → Security Groups** → Select the SG attached to the instance.
2. **Outbound rules** → **Edit outbound rules**.
3. **Remove** the rule “All traffic” to 0.0.0.0/0.
4. **Add rules:**

   | Type        | Protocol | Port range | Destination   | Description        |
   |------------|----------|------------|---------------|--------------------|
   | HTTPS      | TCP      | 443        | 0.0.0.0/0     | Application APIs   |
   | HTTP       | TCP      | 80         | 169.254.169.254/32 | Instance metadata |
   | Custom TCP | TCP      | 53         | 0.0.0.0/0     | DNS TCP            |
   | Custom UDP | UDP      | 53         | 0.0.0.0/0     | DNS UDP            |

   If the VPC uses the default VPC DNS resolver (e.g. 169.254.169.253 or .2), you can set destination to that /32 instead of 0.0.0.0/0 for port 53.

5. **Save** rules.

**Ubuntu / apt:** A1 allows TCP 80 only to 169.254.169.254, so `apt update` over HTTP will fail. On Ubuntu instances, switch apt to HTTPS (port 443) so updates work without opening port 80. See **RUNBOOK_EGRESS_OPTION_A1.md** section 3.1 or run `scripts/aws/apt-sources-https.sh` on the instance via SSM.

**Trade-offs:**

- **Pros:** Simple, no dependency on third-party IP lists, application egress_guard continues to limit which domains are called.
- **Cons:** Egress to any IP on 443 is allowed; a bug or bypass in the guard could allow unwanted calls.

**Risks of over-restricting:**  
If you lock 443 down to a small set of IPs (A2), a provider (e.g. Crypto.com, Telegram) changing IPs or using new CDN nodes can break trading or alerts without any code change. So A2 is only recommended if you have automated updates of prefix lists or accept operational risk.

---

## 3. OPTION B — Advanced hardening (VPC endpoints, NACL, DNS)

**Idea:** Use VPC endpoints where possible (AWS services), restrict remaining egress by domain via DNS or proxy, and optionally add NACL for defense in depth.

### 3.1 VPC endpoints (AWS services only)

- **SSM:** Use **VPC endpoints** for SSM, EC2 messages, and SSM messages so the instance does not need internet for Session Manager.
  - Create interface endpoints in the instance subnets for:
    - `com.amazonaws.<region>.ssm`
    - `com.amazonaws.<region>.ec2messages`
    - `com.amazonaws.<region>.ssmmessages`
  - Attach a security group that allows inbound 443 from the instance SG (or VPC CIDR).
  - After this, you can remove outbound 443 to the internet for SSM; traffic stays inside AWS.

- **ECR (if used):** Create VPC endpoint for `com.amazonaws.<region>.ecr.api` and `com.amazonaws.<region>.ecr.dkr` so `docker pull` does not need internet.

- **S3 (if used for backups or config):** Gateway endpoint for S3 (no cost, no ENI).

### 3.2 NACL (optional, defense in depth)

- NACLs are stateless and use CIDR only (no FQDN).
- You can add a **deny** rule for high-risk ports (e.g. IRC, mining, or other non-required ports) and allow 443, 80 to metadata, 53, 123 (NTP) as needed.
- Do **not** rely on NACL to restrict “which HTTPS host” — that stays in SG + app (and optionally DNS/proxy).

### 3.3 DNS-based restriction (optional)

- Run a local DNS resolver (e.g. Pi-hole, or a small proxy) that resolves only allowlisted domains and returns NXDOMAIN or a sink for others; point the instance to this resolver.
- Or use a commercial “secure web gateway” that allows only FQDNs you list; EC2 egress goes through it.
- **Trade-off:** More complexity and ops; precise control by domain without opening 443 to 0.0.0.0/0.

### 3.4 Exact steps (Option B — summary)

1. **VPC Endpoints (SSM):**
   - VPC → Endpoints → Create endpoint.
   - Services: `com.amazonaws.<region>.ssm`, `com.amazonaws.<region>.ec2messages`, `com.amazonaws.<region>.ssmmessages`.
   - VPC and subnets: same as instance; enable private DNS for each.
   - Security group: allow inbound 443 from instance SG (or VPC CIDR).
   - After validation, SG outbound can drop generic “SSM to internet” if you had added it for SSM.

2. **VPC Endpoints (ECR)** if you use ECR:
   - Create interface endpoints for `ecr.api` and `ecr.dkr`; enable private DNS.
   - SG: allow 443 from instance.

3. **NACL (optional):**
   - Add deny rules for ports you want to block (e.g. 8333, 25, etc.), then allow 443, 80 (only to metadata in practice is hard in NACL), 53, 123 as needed. Default allow can remain for simplicity if SG is the main control.

4. **DNS:** Prefer VPC default DNS (e.g. 169.254.169.253) for resolution; no need to allow 0.0.0.0/0 on 53 if using only VPC resolver.

**Trade-offs:**

- **Pros:** SSM and ECR traffic stays in AWS; can reduce “blast radius” of outbound 443 to internet.
- **Cons:** More moving parts; NACL and DNS tricks do not replace application egress_guard for “which domain.”

**Risks of over-restricting:**  
Same as Option A for third-party IPs. Adding NACL or DNS denials that block 443 to CDN IPs used by Crypto.com/Telegram will break production.

---

## 4. Recommendation summary

| Approach | Use when |
|----------|----------|
| **Option A (A1)** | You want a single, low-friction change: restrict outbound to “only needed ports” (443, 80 to metadata, 53) and keep egress_guard as the domain-level control. |
| **Option A (A2)** | You explicitly accept maintaining IP/prefix lists for third parties and the risk of breakage when they change. |
| **Option B** | You want SSM (and optionally ECR) off the public internet and are fine with VPC endpoint setup and a bit more ops. |

**Suggested path:** Implement **Option A (A1)** first (remove “all traffic” egress, allow only 443, 80 to 169.254.169.254, 53). Then add **Option B** VPC endpoints for SSM (and ECR if used) so the only “broad” egress is HTTPS 443 for application APIs, with application-layer allowlist (egress_guard) defining which domains are used.

---

## 5. Application egress allowlist (reference)

The repo already centralizes allowed domains in `backend/app/utils/egress_guard.py` (`ALLOWLISTED_DOMAINS`). For egress hardening to align with reality, the following should be allowlisted if not already:

- `api.crypto.com` (already)
- `stream.crypto.com` (for WebSocket; add if USE_WEBSOCKET is used)
- `api.telegram.org` (already)
- `api.ipify.org`, `icanhazip.com` (already / add if used)
- `ifconfig.me` (add if diagnose scripts are run in production)
- `api.binance.com`, `api.kraken.com`, `api.coinpaprika.com`, `api.coingecko.com` (add if market_updater / price_fetcher / data_sources use them in production)
- `api.github.com` (add if GITHUB_TOKEN is set)

Adding missing domains to `egress_guard.py` is a small code change; if the brief says “do not modify application code,” then document these as “recommended allowlist additions” and leave implementation for a follow-up change.

---

*Document generated from repository analysis. No application code was modified.*
