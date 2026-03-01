#!/usr/bin/env sh
# Ensure .env.aws exists so compose does not fail on "env file .env.aws not found".
# Call before docker compose in selfheal or deploy.
# Usage: from repo root, or pass REPO_DIR: REPO_DIR=/path ./scripts/aws/ensure_env_aws.sh
# Prints what it did (Created / Already exists). Never prints secrets.
set -eu

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$REPO_DIR"

if [ -f .env.aws ]; then
  echo ".env.aws already exists"
  exit 0
fi

if [ -f .env ]; then
  cp .env .env.aws
  echo "Created .env.aws from .env"
  exit 0
fi

if [ -f .env.example ]; then
  cp .env.example .env
  cp .env.example .env.aws
  echo "Created .env and .env.aws from .env.example"
  exit 0
fi

echo "Warning: no .env or .env.example; .env.aws not created" >&2
exit 0
