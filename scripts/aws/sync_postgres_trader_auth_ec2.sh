#!/usr/bin/env bash
# Run ONLY on EC2: cd /home/ubuntu/crypto-2.0 && bash scripts/aws/sync_postgres_trader_auth_ec2.sh
# Rotates trader password (hex, URL-safe), writes .env.aws, recreates backend-aws.
# Does NOT delete volumes or re-init Postgres data.
set -euo pipefail

ROOT="${1:-/home/ubuntu/crypto-2.0}"
cd "$ROOT" || { echo "ERROR: cd $ROOT failed"; exit 1; }

ENV_AWS="$ROOT/.env.aws"
COMPOSE=(docker compose --profile aws)

echo "== Step 1: project = $ROOT"

if ! "${COMPOSE[@]}" ps -q db >/dev/null 2>&1; then
  echo "ERROR: db service not running. Start stack first."
  exit 1
fi

NEW_PW="$(openssl rand -hex 24)"
export SYNC_PG_NEW_PW="$NEW_PW"

echo "== Step 2: ALTER USER trader (password not printed)"
run_alter() {
  printf "ALTER USER trader WITH PASSWORD '%s';\n" "$SYNC_PG_NEW_PW" | "${COMPOSE[@]}" exec -T db psql -U trader -d atp -v ON_ERROR_STOP=1
}

if ! run_alter; then
  echo "WARN: retry with PGPASSWORD from container env"
  "${COMPOSE[@]}" exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U trader -d atp -v ON_ERROR_STOP=1' <<EOF
ALTER USER trader WITH PASSWORD '$SYNC_PG_NEW_PW';
EOF
fi

echo "== Step 3: update .env.aws (POSTGRES_PASSWORD + DATABASE_URL)"
export SYNC_PG_ROOT="$ROOT"
python3 <<'PY'
from pathlib import Path
import os
import re
from urllib.parse import quote

new_pw = os.environ["SYNC_PG_NEW_PW"]
path = Path(os.environ["SYNC_PG_ROOT"]) / ".env.aws"

lines: list[str] = []
if path.is_file():
    lines = path.read_text(encoding="utf-8").splitlines()

def set_or_append(key: str, value: str) -> None:
    global lines
    pat = re.compile(rf"^{re.escape(key)}=")
    out: list[str] = []
    found = False
    for line in lines:
        if pat.match(line):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    lines = out

db_url = "postgresql://trader:" + quote(new_pw, safe="") + "@db:5432/atp"
set_or_append("POSTGRES_PASSWORD", new_pw)
set_or_append("DATABASE_URL", db_url)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("Wrote", path)
PY

chmod 600 "$ENV_AWS" 2>/dev/null || true

echo "== Step 4: recreate backend-aws"
"${COMPOSE[@]}" up -d --force-recreate backend-aws

echo "== Step 5: wait for backend"
sleep 15

echo "== Step 6: validate SQLAlchemy SELECT 1"
if ! "${COMPOSE[@]}" exec -T backend-aws python3 -c "
from sqlalchemy import create_engine, text
import os
e = create_engine(os.environ['DATABASE_URL'], pool_pre_ping=True)
with e.connect() as c:
    r = c.execute(text('SELECT 1')).scalar()
    assert r == 1, r
print('OK SELECT 1 =', r)
"; then
  echo "== VALIDATION FAILED — backend-aws logs (tail 80) =="
  "${COMPOSE[@]}" logs --tail 80 backend-aws 2>&1 || true
  exit 1
fi

unset SYNC_PG_NEW_PW
echo "== Done."
