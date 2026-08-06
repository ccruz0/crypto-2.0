#!/usr/bin/env bash
# Enable Bumi Beans Graph mailbox on prod brief_mailboxes.json (idempotent).
# Run on EC2 via SSM. Never prints secrets.
set -euo pipefail
REPO="${REPO:-/home/ubuntu/crypto-2.0}"
MB="$REPO/secrets/brief_mailboxes.json"
cd "$REPO"

if [[ ! -f "$MB" ]]; then
  echo "ERROR: missing $MB" >&2
  exit 1
fi

TS=$(date -u +%Y%m%d%H%M%S)
sudo cp -a "$MB" "${MB}.bak.pre-bumi-enable-${TS}"

sudo python3 - <<'PY'
import json
from pathlib import Path
p = Path("secrets/brief_mailboxes.json")
items = json.loads(p.read_text())
changed = False
for item in items:
    if item.get("id") != "bumibeans":
        continue
    if item.get("provider") != "graph":
        item["provider"] = "graph"
        changed = True
    if item.get("enabled") is not True:
        item["enabled"] = True
        changed = True
    user = (item.get("user") or "").strip()
    if not user:
        item["user"] = "carlos.cruz@bumibeans.com"
        changed = True
    # priority bump for morning brief
    if (item.get("priority") or "").strip().lower() == "baja":
        item["priority"] = "alta"
        changed = True
    print(
        "bumibeans",
        "enabled=", item.get("enabled"),
        "provider=", item.get("provider"),
        "user_set=", bool((item.get("user") or "").strip()),
        "changed=", changed,
    )
    break
else:
    raise SystemExit("bumibeans entry missing")
if changed:
    p.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
PY
# Keep mailbox JSON readable by backend appuser (uid 10001), same as other secrets.
sudo chown root:10001 "$MB" 2>/dev/null || true
sudo chmod 640 "$MB" 2>/dev/null || true

# Ensure Graph env is present via render (SSM triad)
sudo bash scripts/aws/render_runtime_env.sh || bash scripts/aws/render_runtime_env.sh
GRAPH_N=$(sudo grep -cE '^BRIEF_GRAPH_(TENANT_ID|CLIENT_ID|CLIENT_SECRET)=' secrets/runtime.env || true)
echo "BRIEF_GRAPH_keys=${GRAPH_N}"
if [[ "${GRAPH_N}" -lt 3 ]]; then
  echo "ERROR: expected 3 BRIEF_GRAPH_* keys in runtime.env after render" >&2
  exit 1
fi

# Recreate backend to pick up new env
sudo docker compose --profile aws up -d --no-deps --force-recreate backend-aws

echo "Waiting healthy..."
ok_health=0
for i in $(seq 1 30); do
  st=$(docker inspect automated-trading-platform-backend-aws-1 --format '{{.State.Health.Status}}' 2>/dev/null || echo missing)
  echo "health=$st"
  if [[ "$st" == "healthy" ]]; then
    ok_health=1
    break
  fi
  sleep 5
done
if [[ "$ok_health" != "1" ]]; then
  echo "ERROR: backend-aws not healthy after recreate" >&2
  exit 1
fi

BRIEF_KEY=$(sudo grep -E '^BRIEF_API_KEY=' secrets/runtime.env | head -1 | cut -d= -f2-)
test -n "$BRIEF_KEY"
mail_code=$(curl -sS -o /tmp/bumi_mail.json -w '%{http_code}' --max-time 60 \
  -H "X-Brief-Key: $BRIEF_KEY" \
  'https://dashboard.hilovivo.com/api/brief/mail?hours=24' || echo 000)
echo "mail:${mail_code}"
if [[ "$mail_code" != "200" ]]; then
  echo "ERROR: /api/brief/mail returned HTTP ${mail_code}" >&2
  head -c 400 /tmp/bumi_mail.json 2>/dev/null || true
  echo
  exit 1
fi
python3 - <<'PY'
import json
import sys
from pathlib import Path
d=json.loads(Path('/tmp/bumi_mail.json').read_text())
ids=[a.get('id') for a in d.get('accounts') or []]
print('account_ids=', ids)
print('bumibeans_in_accounts=', 'bumibeans' in ids)
errs=[e for e in (d.get('errors') or []) if e.get('id')=='bumibeans']
print('bumibeans_errors=', errs)
if 'bumibeans' in ids:
    acct=next(a for a in d['accounts'] if a['id']=='bumibeans')
    print('bumibeans_count=', acct.get('count'))
if errs:
    print('ERROR: bumibeans present in errors (Graph auth/consent?)', file=sys.stderr)
    for e in errs:
        print(f"  detail={e}", file=sys.stderr)
    sys.exit(1)
if 'bumibeans' not in ids:
    print('ERROR: bumibeans missing from accounts', file=sys.stderr)
    sys.exit(1)
print('OK: bumibeans Graph mailbox enabled')
PY
