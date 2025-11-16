#!/usr/bin/env bash

set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"

cd "$HERE"

python3 -m venv .venv-audit

source .venv-audit/bin/activate

pip install --upgrade pip
pip install "pip-audit>=2.7" "safety>=3.2"

echo "🔍 Running pip-audit..."
pip-audit -r requirements.txt || true

echo "🔍 Running safety check..."
safety check -r requirements.txt || true

deactivate
rm -rf .venv-audit

