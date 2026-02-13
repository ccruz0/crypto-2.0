#!/usr/bin/env bash
# EC2: Diagnostic for DB reachability and order_intents table.
# No secrets printed. No docker compose config.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "Repo path: $ROOT"
echo "git short HEAD: $(git rev-parse --short HEAD 2>/dev/null || echo '(no-git)')"
echo ""
docker compose --profile aws ps 2>/dev/null || true
echo ""

set +e
docker compose --profile aws exec -T backend-aws python - <<'PY'
import os
import socket
import sys

dsn = (os.getenv("DATABASE_URL") or "").strip()
if not dsn:
    print("FAIL: DATABASE_URL not set")
    sys.exit(1)

# Redact password: user:pass@ -> user:***@
if "://" in dsn and "@" in dsn:
    before_at = dsn.split("@", 1)[0]
    if ":" in before_at:
        prefix, _ = before_at.split("://", 1)
        user_part = before_at.split("://", 1)[1]
        if ":" in user_part:
            user = user_part.rsplit(":", 1)[0]
            redacted = dsn.replace(user_part + "@", user + ":***@", 1)
        else:
            redacted = dsn
    else:
        redacted = dsn
else:
    redacted = dsn
print("DATABASE_URL (redacted):", redacted)

# Parse host and port (postgresql:// or postgres://)
if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
    rest = dsn.split("://", 1)[1]
else:
    rest = dsn
if "@" in rest:
    netloc = rest.split("@", 1)[1].split("/")[0]
else:
    netloc = rest.split("/")[0]
if ":" in netloc:
    parsed_host, parsed_port_s = netloc.rsplit(":", 1)
    parsed_port = int(parsed_port_s)
else:
    parsed_host = netloc
    parsed_port = 5432
print("DB host:", parsed_host)
print("DB port:", parsed_port)

# TCP connectivity (3s timeout)
def tcp_check(name, host, port, timeout=3):
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        print("TCP_OK", name, f"{host}:{port}")
    except Exception:
        print("TCP_FAIL", name, f"{host}:{port}")

tcp_check("db", "db", 5432)
tcp_check("postgres_hardened", "postgres_hardened", 5432)
tcp_check("postgres_hardened_backup", "postgres_hardened_backup", 5432)
tcp_check("parsed_host", parsed_host, parsed_port)

# DB connect via SQLAlchemy
try:
    from sqlalchemy import create_engine, text
    engine = create_engine(dsn, pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("select 1"))
except Exception as e:
    print("FAIL: DB_CONNECT failed")
    print("HINT: DATABASE_URL likely using stale IP; use service name 'db' instead.")
    sys.exit(1)

# order_intents check
with engine.connect() as conn:
    r = conn.execute(text("select to_regclass('public.order_intents')")).scalar()
print("order_intents_regclass=", r, sep="")
if r is None:
    print("FAIL: order_intents missing")
    sys.exit(1)
print("PASS: order_intents exists")
sys.exit(0)
PY
code=$?
set -e
echo "exit=$code"
exit $code
