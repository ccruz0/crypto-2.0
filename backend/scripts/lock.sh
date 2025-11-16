#!/usr/bin/env bash

set -euo pipefail

# Always run from repo root context passed in
HERE="$(cd "$(dirname "$0")/.." && pwd)"

cd "$HERE"

# Isolate a temp venv to resolve packages
python3 -m venv .venv-lock

# shellcheck disable=SC1091
source .venv-lock/bin/activate

pip install --upgrade pip
pip install "pip-tools>=7.4" "pip-audit>=2.7" "safety>=3.2"

# 1) Resolver baseline a constraints con hashes (sin forzar upgrades)
pip-compile --generate-hashes --allow-unsafe \
  --output-file constraints.txt \
  -r requirements.txt

# 2) Auditar requirements; si hay vulnerables, subir SOLO paquetes afectados a último parche compatible
#    Estrategia: obtener lista de paquetes vulnerables y ejecutar pip-compile --upgrade-package por cada uno.
VULN_PKGS_JSON="$(pip-audit -r requirements.txt -f json || true)"

python3 - <<'PY'
import json
import os
import sys

data = os.environ.get("VULN_PKGS_JSON", "")
if not data.strip():
    sys.exit(0)

try:
    report = json.loads(data)
except Exception:
    sys.exit(0)

# Recolectar nombres únicos de paquetes vulnerables
names = []
for item in report.get("dependencies", []):
    if item.get("vulns"):
        name = item.get("name")
        if name and name.lower() not in [n.lower() for n in names]:
            names.append(name)

if not names:
    sys.exit(0)

# Escribir lista para el siguiente paso
with open(".vuln-upgrade-list.txt", "w") as f:
    for n in names:
        f.write(n + "\n")

print(f"Packages to upgrade (patch/minor): {', '.join(names)}")
PY

if [[ -f ".vuln-upgrade-list.txt" ]]; then
  while IFS= read -r pkg; do
    # Intentar subir solo ese paquete (parche/minor) y regenerar constraints
    pip-compile --generate-hashes --allow-unsafe \
      --upgrade-package "$pkg" \
      --output-file constraints.txt \
      -r requirements.txt
  done < .vuln-upgrade-list.txt
  rm -f .vuln-upgrade-list.txt
fi

# 3) Validar resultado final con una instalación simulada
pip install -r constraints.txt

echo "✅ constraints.txt actualizado correctamente."

deactivate
rm -rf .venv-lock

