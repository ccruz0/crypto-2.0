#!/usr/bin/env bash
# Verify deploy secrets are loaded in the running backend-aws container.
# Reports presence only (never values). Use after deploy to confirm GitHub auth is available.
#
# Usage:
#   ./scripts/verify_deploy_secrets.sh
#   # On EC2 via SSM:
#   aws ssm send-command --instance-ids i-xxx --document-name AWS-RunShellScript \
#     --parameters 'commands=["cd ~/crypto-2.0 && ./scripts/verify_deploy_secrets.sh"]' ...

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/.."
cd "$ROOT_DIR"

# Prefer the exact compose service backend-aws (prod) — this cannot match
# backend-aws-canary. Fall back to name filters (excluding canary), then
# backend, then backend-dev (local).
CONTAINER="$(docker compose --profile aws ps -q backend-aws 2>/dev/null | head -1 || true)"
[[ -z "$CONTAINER" ]] && CONTAINER="$(docker ps --filter 'name=backend-aws' --format '{{.ID}} {{.Names}}' | awk '$2 !~ /canary/ {print $1; exit}')"
[[ -z "$CONTAINER" ]] && CONTAINER="$(docker ps --filter 'name=automated-trading-platform-backend' --format '{{.ID}} {{.Names}}' | awk '$2 !~ /canary/ {print $1; exit}')"
[[ -z "$CONTAINER" ]] && CONTAINER="$(docker ps -q --filter 'name=backend-dev' | head -1)"

if [[ -z "$CONTAINER" ]]; then
  echo "ERROR: No backend container running (backend-aws, backend, or backend-dev)" >&2
  echo "" >&2
  echo "Host file check (secrets/runtime.env):" >&2
  if [[ -f secrets/runtime.env ]]; then
    for key in GITHUB_APP_ID GITHUB_APP_INSTALLATION_ID GITHUB_APP_PRIVATE_KEY_B64 GITHUB_TOKEN; do
      if grep -q "^${key}=" secrets/runtime.env 2>/dev/null; then
        echo "  ${key}: present in file" >&2
      else
        echo "  ${key}: MISSING in file" >&2
      fi
    done
  else
    echo "  secrets/runtime.env not found" >&2
  fi
  echo "" >&2
  echo "Start a backend with: docker compose --profile local up -d backend-dev" >&2
  exit 1
fi

CONTAINER_NAME="$(docker ps --filter "id=$CONTAINER" --format '{{.Names}}')"
echo "Using container: $CONTAINER_NAME"

echo "== Deploy secrets (container env, presence only) =="
docker exec -i "$CONTAINER" python3 - <<'PY'
import os

def present(name):
    return "yes" if bool((os.getenv(name) or "").strip()) else "no"

app_keys = [
    "GITHUB_APP_ID",
    "GITHUB_APP_INSTALLATION_ID",
    "GITHUB_APP_PRIVATE_KEY_B64",
]
app_ready = all(present(k) == "yes" for k in app_keys)
legacy_ready = (
    (os.getenv("ALLOW_LEGACY_GITHUB_PAT") or "").strip().lower() in ("1", "true", "yes", "on")
    and present("GITHUB_TOKEN") == "yes"
)

print("  GitHub App credentials:")
for key in app_keys:
    print(f"    {key}: {present(key)}")
print(f"  GitHub App ready (all three): {'yes' if app_ready else 'no'}")
print(f"  ALLOW_LEGACY_GITHUB_PAT: {present('ALLOW_LEGACY_GITHUB_PAT')}")
print(f"  GITHUB_TOKEN (legacy): {present('GITHUB_TOKEN')}")
print(f"  Legacy PAT path ready: {'yes' if legacy_ready else 'no'}")
if app_ready:
    print("  auth_mode: github_app")
elif legacy_ready:
    print("  auth_mode: legacy_transition")
else:
    print("  auth_mode: none")

for key, desc in [
    ("GITHUB_WEBHOOK_SECRET", "optional, for webhook signature verification"),
    ("OPENCLAW_API_TOKEN", "optional, for OpenClaw integration"),
]:
    print(f"  {key}: {present(key)} ({desc})")

if not app_ready and not legacy_ready:
    print("  ^^^ DEPLOY AUTOMATION NOT READY - configure GITHUB_APP_* or legacy PAT escape hatch")
PY

echo
echo "== Deploy automation ready? =="
AUTH_READY=$(docker exec -i "$CONTAINER" python3 - <<'PY'
import os

def ok(name):
    return bool((os.getenv(name) or "").strip())

app = ok("GITHUB_APP_ID") and ok("GITHUB_APP_INSTALLATION_ID") and ok("GITHUB_APP_PRIVATE_KEY_B64")
legacy = (
    (os.getenv("ALLOW_LEGACY_GITHUB_PAT") or "").strip().lower() in ("1", "true", "yes", "on")
    and ok("GITHUB_TOKEN")
)
print("yes" if app or legacy else "no")
PY
)
if [[ "$AUTH_READY" == "yes" ]]; then
  echo "  YES - GitHub App or legacy PAT configured; deploy trigger from Telegram should work"
  exit 0
else
  echo "  NO - GitHub auth missing. Run: bash scripts/aws/render_runtime_env.sh"
  echo "  Then: docker compose --profile aws up -d --force-recreate backend-aws"
  exit 1
fi
