# OpenClaw HIGH-SECURITY LEVEL 2 Setup

This document describes how to run OpenClaw in HIGH-SECURITY LEVEL 2 mode: the agent runs inside Docker with outbound traffic restricted to `https://api.openai.com` only.

## Architecture

- **openclaw-agent**: A Python container that mounts the repository and runs the agent. All HTTP/HTTPS traffic is forced through the egress proxy via `HTTP_PROXY` / `HTTPS_PROXY`.
- **egress-proxy**: A Squid proxy that allows only CONNECT requests to `api.openai.com` on port 443. All other destinations and non-HTTPS traffic are denied.

The agent has no direct internet access; every outbound request goes through Squid, which enforces the allowlist.

## Security Rationale

- **Single egress path**: Only the proxy can reach the network; the agent container does not need external network access.
- **Allowlist-only**: Squid is configured with `acl allowed_dstdomain dstdomain api.openai.com` and `http_access allow allowed_dstdomain` then `http_access deny all`, so only that host is permitted.
- **No production secrets**: The setup uses a file-based Docker secret for the OpenAI key (no key in chat, env, or logs). Do not mount `~/.ssh`, `~/.aws`, or use production credentials.
- **Isolated network**: Both services run on a dedicated Docker network (`claw_net`); the proxy is the only path to the internet.

## Prerequisites

- Docker and Docker Compose (v2) installed.
- A dedicated OpenAI API key for OpenClaw (not a production key).

## Secure key entry (no chat, no logs)

Keys are never pasted into chat, printed, or committed. Use local hidden input and a Docker secret file.

**Steps:**

**a) Run the secret prompt** (from repository root). You will be prompted for `OPENAI_API_KEY` with hidden input (no echo):

```bash
bash security/openclaw/secret_prompt.sh
```

This creates `security/openclaw/.openai_api_key` (mode 0600, gitignored). The key is not printed or logged.

**Rotate key:** To replace an existing key, run:

```bash
bash security/openclaw/secret_prompt.sh --rotate
```

**b) Start the proxy**

```bash
docker compose -f security/openclaw/docker-compose.openclaw.yml up -d egress-proxy
```

Wait a few seconds for Squid to start, then optionally check logs:

```bash
docker compose -f security/openclaw/docker-compose.openclaw.yml logs egress-proxy
```

**c) Run the agent**

To start the stack (proxy + agent) in the background:

```bash
docker compose -f security/openclaw/docker-compose.openclaw.yml up -d
```

To run an interactive shell inside the agent container (e.g. to install and run OpenClaw manually):

```bash
docker compose -f security/openclaw/docker-compose.openclaw.yml run --rm openclaw-agent bash
```

The repository is mounted at `/repo` inside the container.

### d) Test that only `api.openai.com` is reachable

From the host, traffic through the proxy can be tested with `curl`:

- **Should succeed** (allowed domain, HTTPS):

  ```bash
  curl -x http://127.0.0.1:3128 -sS -o /dev/null -w "%{http_code}" https://api.openai.com/
  ```
  You should get a response (e.g. 200 or 401 without a key), not a proxy denial.

- **Should be denied** (blocked by Squid):

  ```bash
  curl -x http://127.0.0.1:3128 -sS -o /dev/null -w "%{http_code}" https://www.google.com/
  ```
  Access should be denied (e.g. 403 from Squid or connection error).

To test from inside the agent container (with the stack running):

```bash
docker compose -f security/openclaw/docker-compose.openclaw.yml run --rm openclaw-agent bash -c '
  apt-get update -qq && apt-get install -qq -y curl > /dev/null
  echo "Testing api.openai.com (should work):"
  curl -sS -o /dev/null -w "%{http_code}\n" https://api.openai.com/ || true
  echo "Testing google.com (should fail):"
  curl -sS -o /dev/null -w "%{http_code}\n" https://www.google.com/ || true
'
```

Allowed traffic should complete; other hosts should be blocked by the proxy.

### Validate API key (masked output only)

Run inside the agent container. Uses stdlib only (no `pip install`). The key is read from `OPENAI_API_KEY_FILE`; only status code and a masked key (first 4 + last 4 chars) are printed:

```bash
docker compose -f security/openclaw/docker-compose.openclaw.yml run --rm openclaw-agent bash -c '
python - << "PY"
import os, urllib.request

path = os.getenv("OPENAI_API_KEY_FILE", "/run/secrets/openai_api_key")
key = open(path, "r", encoding="utf-8").read().strip()
masked = (key[:4] + "..." + key[-4:]) if len(key) > 8 else "INVALID"
print("Key (masked):", masked)

req = urllib.request.Request(
  "https://api.openai.com/v1/models",
  headers={"Authorization": f"Bearer {key}"}
)
try:
  with urllib.request.urlopen(req, timeout=15) as r:
    print("OpenAI status:", r.status)
except Exception as e:
  print("OpenAI call failed:", type(e).__name__)
PY
'
```

**Save evidence locally (no secrets):** Run the capture script to write `docker compose ps` and the masked OpenAI test result to `docs/openclaw/OPENCLAW_EVIDENCE_YYYYMMDD_HHMMSS.txt`:

```bash
bash security/openclaw/validate_and_capture.sh
```

## Warnings

- **Do not mount `~/.ssh` or `~/.aws`** into the OpenClaw agent container. The default compose file mounts only the repository (`../../:/repo`). Adding host SSH or AWS directories would expose production credentials and violate the high-security model.
- **Do not use production credentials.** Use a dedicated, non-production OpenAI API key. The key is stored only in the secret file (never in chat or logs).

## File layout

- `security/openclaw/squid.conf` – Squid egress proxy configuration.
- `security/openclaw/docker-compose.openclaw.yml` – Compose file for egress-proxy and openclaw-agent (uses file-based secret).
- `security/openclaw/secret_prompt.sh` – Prompts for API key with hidden input and writes `security/openclaw/.openai_api_key`.
- `security/openclaw/.openai_api_key` – Secret file (gitignored); created by `secret_prompt.sh`, mounted in container at `/run/secrets/openai_api_key`.

OpenClaw itself is not installed by this setup; install and run it inside the agent container as needed.
