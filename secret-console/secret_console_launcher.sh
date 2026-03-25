#!/usr/bin/env bash
# Secret Console — macOS launcher (idempotent: safe to run repeatedly).
# Resolves project dir, ensures .venv and dependencies, runs uvicorn, opens the UI.

set -euo pipefail

PORT="${SECRET_CONSOLE_PORT:-8765}"
HOST="${SECRET_CONSOLE_HOST:-127.0.0.1}"

PROJECT_DIR=""
for candidate in "$HOME/secret-console" "$HOME/automated-trading-platform/secret-console"; do
  if [[ -d "$candidate" ]] && [[ -f "$candidate/app.py" ]] && [[ -f "$candidate/requirements.txt" ]]; then
    PROJECT_DIR="$candidate"
    break
  fi
done

if [[ -z "$PROJECT_DIR" ]]; then
  echo "secret-console: project directory not found." >&2
  echo "Looked for (each must contain app.py and requirements.txt):" >&2
  echo "  - \$HOME/secret-console" >&2
  echo "  - \$HOME/automated-trading-platform/secret-console" >&2
  exit 1
fi

cd "$PROJECT_DIR"
echo "Using project: $PROJECT_DIR"

VENV_DIR="$PROJECT_DIR/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating virtual environment: $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

PIP="$VENV_DIR/bin/pip"
PY="$VENV_DIR/bin/python3"
if [[ ! -x "$PY" ]]; then
  echo "Invalid venv (missing python): $VENV_DIR" >&2
  exit 1
fi

echo "Installing / updating dependencies (requirements.txt)…"
"$PIP" install -q -r "$PROJECT_DIR/requirements.txt"

URL="http://${HOST}:${PORT}/"
if command -v nc >/dev/null 2>&1; then
  if nc -z "$HOST" "$PORT" 2>/dev/null; then
    echo "Something is already listening on ${HOST}:${PORT}; opening browser only."
    open "$URL" 2>/dev/null || true
    exit 0
  fi
fi

echo "Starting Secret Console on ${URL}"
echo "Press Ctrl+C to stop."

# Open dashboard shortly after the server starts (best-effort).
( sleep 2 && open "$URL" 2>/dev/null || true ) &

exec "$PY" -m uvicorn app:app --host "$HOST" --port "$PORT" --reload
