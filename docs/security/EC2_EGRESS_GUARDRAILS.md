# EC2 Egress Guardrails

This document describes the security guardrails in place to prevent unauthorized outbound network traffic from our EC2 instances.

## Overview

To prevent outbound "active scanning" patterns and ensure all external connections are legitimate, we enforce:

1. **Egress Allowlist**: Only allowlisted domains can be accessed
2. **Raw IP Blocking**: Direct IP address connections are blocked by default
3. **Security Logging**: All outbound requests are logged with destination, resolved IP, and calling module
4. **Single Entry Point**: All outbound HTTP requests MUST use `app.utils.http_client` - this is the ONLY allowed entry point

## Implementation

The egress guardrails are implemented in `backend/app/utils/egress_guard.py` and enforced through the mandatory HTTP client wrapper `backend/app/utils/http_client.py`:

- **http_client.py**: Single mandatory entry point for all outbound HTTP requests
  - All URLs are validated BEFORE DNS resolution and connection
  - Redirects are disabled by default to prevent redirect attacks
  - If redirects are enabled, the final destination is validated against the allowlist
- **VPN Gate** (`backend/app/utils/vpn_gate.py`): Uses http_client for health checks
- **Data Sources** (`backend/app/services/data_sources.py`): Uses http_client for API data fetching
- **Crypto.com Trade Client** (`backend/app/services/brokers/crypto_com_trade.py`): Uses http_client for exchange API calls
- **Crypto.com Constants** (`backend/app/services/brokers/crypto_com_constants.py`): Raw IP usage is disabled

## Redirect Handling

HTTP redirects pose a security risk because they can be used to bypass the egress allowlist. For example, an allowlisted domain could redirect to a malicious non-allowlisted domain.

**Protection Strategy:**

1. **Redirects Disabled by Default**: All HTTP requests have `allow_redirects=False` by default
2. **Explicit Enable Required**: Redirects must be explicitly enabled via `allow_redirects=True`
3. **Final Destination Validation**: When redirects are enabled, the final destination URL (after all redirects) is validated against the egress allowlist
4. **Request Blocked on Invalid Redirect**: If a redirect leads to a non-allowlisted domain, the request is immediately blocked and the connection is closed

**Example:**
```python
# Redirects disabled by default (secure)
response = http_get("https://api.crypto.com/exchange/v1", calling_module="my_module")

# Redirects explicitly enabled - final destination will be validated
response = http_get(
    "https://api.crypto.com/exchange/v1",
    allow_redirects=True,  # Must be explicit
    calling_module="my_module"
)
# If redirect goes to evil.com, request is blocked with EgressGuardError
```

## Allowlisted Domains

The following domains are currently allowlisted for outbound connections:

- `api.crypto.com` - Crypto.com Exchange API
- `api.coingecko.com` - CoinGecko API for price data
- `api.telegram.org` - Telegram Bot API
- `api.ipify.org` - IP checking service (for diagnostics)
- `icanhazip.com` - IP checking service (for diagnostics)
- `dashboard.hilovivo.com` - Our dashboard domain
- `hilovivo.com` - Our main domain

## AWS Security Group Configuration

### Recommended Outbound Rules

Configure your EC2 Security Group with restrictive outbound rules:

```
# HTTPS to allowlisted domains
- Type: HTTPS (443)
  Protocol: TCP
  Port: 443
  Destination: Specific IPs or domain-based rules
  
# DNS (required for domain resolution)
- Type: DNS (UDP)
  Protocol: UDP
  Port: 53
  Destination: VPC DNS resolver or 8.8.8.8/8.8.4.4

# HTTP (only if needed for internal services)
- Type: HTTP (80)
  Protocol: TCP
  Port: 80
  Destination: Internal services only (optional)
```

### Security Group Best Practices

1. **Principle of Least Privilege**: Only allow outbound to specific IPs/domains required
2. **HTTPS Only**: Prefer HTTPS (443) over HTTP (80) for external services
3. **No 0.0.0.0/0**: Never allow all outbound traffic (0.0.0.0/0)
4. **IP-based Rules**: For critical services like Crypto.com API, consider IP-based rules if they publish their IP ranges

### Example Security Group Configuration

```
Outbound Rules:
┌─────────────────────────────────────────────────────────────┐
│ Rule ID │ Type  │ Protocol │ Port │ Destination             │
├─────────┼───────┼──────────┼──────┼─────────────────────────┤
│ sg-001  │ HTTPS │ TCP      │ 443  │ api.crypto.com/32       │
│ sg-002  │ HTTPS │ TCP      │ 443  │ api.coingecko.com/32    │
│ sg-003  │ HTTPS │ TCP      │ 443  │ api.telegram.org/32     │
│ sg-004  │ HTTPS │ TCP      │ 443  │ api.ipify.org/32        │
│ sg-005  │ DNS   │ UDP      │ 53   │ VPC DNS resolver        │
└─────────────────────────────────────────────────────────────┘
```

Note: The `/32` notation indicates a single IP address. In practice, you may need to resolve domains to their current IP addresses, or use AWS Security Group rules with domain names if your AWS setup supports it.

## Single Entry Point: http_client.py

**CRITICAL**: `backend/app/utils/http_client.py` is the ONLY allowed entry point for outbound HTTP requests in the backend.

**DO NOT:**
- Use `requests.get()` or `requests.post()` directly
- Use `aiohttp.ClientSession` directly
- Use `urllib.request` directly
- Import `requests`, `aiohttp`, or `urllib.request` outside `http_client.py`

**DO:**
- Import: `from app.utils.http_client import http_get, http_post, async_http_get`
- Use these functions for all outbound HTTP requests
- All URLs are automatically validated against the egress allowlist

The CI pipeline enforces this with static checks that fail if direct HTTP library imports or calls are detected outside `http_client.py`.

## Verification

### Verify Egress from Inside Container

To verify what outbound connections are being made:

```bash
# SSH to EC2 instance
ssh hilovivo-aws

# Check active connections
ss -tupn | grep ESTAB

# Monitor outbound connections
sudo tcpdump -i any -n 'tcp and (dst port 443 or dst port 80)' | head -50

# Check Docker container connections
docker compose exec backend-aws ss -tupn
```

### Run Egress Audit Script

The `scripts/security/egress_audit.py` script validates all configured outbound URLs:

```bash
# From project root
python scripts/security/egress_audit.py
```

This script:
- Checks environment variables for URLs
- Validates docker-compose.yml configuration
- Checks Python constant files
- Reports any raw IP addresses or non-allowlisted domains

### Expected Output

When everything is configured correctly, you should see:

```
======================================================================
EGRESS AUDIT: Checking configured outbound URLs
======================================================================

1. Checking environment variables...
   ✓ VPN_GATE_URL: https://api.crypto.com/exchange/v1/public/get-tickers?instrument_name=BTC_USDT (allowlisted)
   ✓ EXCHANGE_CUSTOM_BASE_URL: https://api.crypto.com/exchange/v1 (allowlisted)
   ...

======================================================================
SUMMARY
======================================================================

✓ No security issues found!
  All configured outbound URLs are allowlisted and use domain names.
```

## Adding New Domains

If you need to add a new domain to the allowlist:

1. Edit `backend/app/utils/egress_guard.py`
2. Add the domain to `ALLOWLISTED_DOMAINS` set
3. Test with `scripts/security/egress_audit.py`
4. Update this documentation

Example:

```python
ALLOWLISTED_DOMAINS: Set[str] = {
    # ... existing domains ...
    "new-service.example.com",  # New service
}
```

## Raw IP Address Usage

**Raw IP addresses are blocked by default** for security reasons. If you have a legitimate need to use a raw IP:

1. Add it to `ALLOWLISTED_IPS` in `egress_guard.py` (only for infrastructure services like metadata endpoints)
2. Document the reason in code comments
3. Prefer domain names whenever possible

Example (infrastructure service only):

```python
ALLOWLISTED_IPS: Set[str] = {
    "169.254.169.254",  # AWS metadata service (required for EC2)
}
```

## Monitoring and Logging

All outbound requests are logged with:

- Destination hostname
- Resolved IP address (if available)
- Calling module/function
- HTTP method and status code
- Correlation ID (if available)

Look for log entries prefixed with `[EGRESS_GUARD]`:

```bash
# View egress guard logs
docker compose logs backend-aws | grep EGRESS_GUARD

# Example log entry:
# [EGRESS_GUARD] Allowed outbound request: api.crypto.com -> 104.19.223.17 (called from crypto_com_trade.get_account_summary)
# [EGRESS_GUARD] SECURITY VIOLATION: Outbound request to raw IP address 147.251.181.222 blocked. ...
```

## Incident Response

If you observe unauthorized outbound traffic:

1. **Immediately check logs**:
   ```bash
   docker compose logs backend-aws | grep -i "egress_guard\|security violation"
   ```

2. **Run audit script**:
   ```bash
   python scripts/security/egress_audit.py
   ```

3. **Check Security Group rules**:
   ```bash
   aws ec2 describe-security-groups --group-ids sg-xxxxx --query 'SecurityGroups[0].IpPermissionsEgress'
   ```

4. **Review recent changes**:
   - Check git history for changes to URLs/IPs
   - Review environment variable changes
   - Check docker-compose.yml changes

5. **Document incident** in `docs/incidents/`

## Related Documentation

- `docs/incidents/2025-12-10_aws_abuse_report.md` - Initial incident report
- `backend/app/utils/egress_guard.py` - Implementation code
- `scripts/security/egress_audit.py` - Audit script

