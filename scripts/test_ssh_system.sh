#!/usr/bin/env bash
set -euo pipefail

# Strict validator for unified SSH usage in operational scripts only.
# Scope (only):
#   - scripts/*.sh
#   - deploy_*.sh
#   - backend/*.sh
# Everything else is ignored (node_modules, docs, tests, examples, etc).

ROOT_DIR="$(cd "$(dirname "$0")/.."; pwd)"
cd "$ROOT_DIR"

pass=true
checked=0
skipped=0
violations_total=0

echo "[CHECK] Verifying helper functions exist..."
if ! grep -q 'ssh_cmd()' scripts/ssh_key.sh || ! grep -q 'scp_cmd()' scripts/ssh_key.sh || ! grep -q 'rsync_cmd()' scripts/ssh_key.sh; then
  echo "  ❌ Missing helper functions in scripts/ssh_key.sh"
  pass=false
else
  echo "  ✅ Helper functions present"
fi

echo "[CHECK] Ensuring operational scripts source the helper..."
missing_source=0
is_excluded_path() {
  case "$1" in
    */node_modules/*|*/examples/*|*/docs/*|*/test/*|*/tests/*|*/__tests__/*|*/tmp/*|*/.github/*|*/.vscode/*|*/assets/*|*/static/*|*/public/*|*/scripts/archive/*|*/scripts/experimental/*)
      return 0;;
    *) return 1;;
  esac
}
files=()
for f in scripts/*.sh deploy_*.sh backend/*.sh; do
  [[ -f "$f" ]] || continue
  if is_excluded_path "$f"; then
    skipped=$((skipped+1))
    continue
  fi
  files+=("$f")
done
for f in "${files[@]}"; do
  checked=$((checked+1))
  rel="${f#$ROOT_DIR/}"
  [[ "$rel" == "scripts/ssh_key.sh" ]] && continue
  if ! grep -E -q 'scripts/ssh_key\.sh' "$f"; then
    # Only require sourcing if the script executes ssh/scp/rsync/ssh-agent/ssh-add
    if grep -E -q '^[[:space:]]*(ssh|scp|rsync|ssh-agent|ssh-add)[[:space:]]' "$f"; then
      echo "  ❌ Missing helper sourcing in $rel"
      pass=false
      missing_source=$((missing_source+1))
    fi
  fi
done
echo "  ✅ Helper sourcing check completed"

echo "[CHECK] Detecting executable raw ssh/scp/rsync calls..."
violations=$(mktemp)
for f in "${files[@]}"; do
  rel="${f#$ROOT_DIR/}"
  [[ "$rel" == "scripts/test_ssh_system.sh" ]] && continue
  heredoc_end=""
  lineno=0
  while IFS= read -r line || [ -n "$line" ]; do
    lineno=$((lineno+1))
    # heredoc detection (skip inner content)
    if [[ -z "$heredoc_end" ]]; then
      token="$(printf '%s\n' "$line" | sed -n 's/.*<<[[:space:]]*\\([A-Za-z0-9_][A-Za-z0-9_]*\\).*/\\1/p')"
      if [[ -n "$token" ]]; then
        heredoc_end="$token"
        continue
      fi
    fi
    if [[ -n "$heredoc_end" ]]; then
      [[ "$line" == "$heredoc_end" ]] && heredoc_end=""
      continue
    fi
    trimmed="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$trimmed" || "$trimmed" =~ ^# ]] && continue
    # Allow echo/printf with ssh examples
    if [[ "$trimmed" =~ ^(echo|printf)[[:space:]].*ssh ]]; then
      continue
    fi
    # Flag only executable raw commands (start of command)
    if [[ "$trimmed" =~ ^(ssh|scp|rsync|ssh-agent|ssh-add)[[:space:]] ]]; then
      echo "  ❌ $rel:$lineno: $trimmed" >> "$violations"
      violations_total=$((violations_total+1))
      pass=false
      continue
    fi
    # Flag .pem only if part of an executable command (not assignment/echo)
    if [[ "$trimmed" =~ \.pem ]] && [[ "$trimmed" =~ ^[A-Za-z0-9_./-]+[[:space:]] ]] && ! [[ "$trimmed" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      echo "  ❌ $rel:$lineno: $trimmed" >> "$violations"
      violations_total=$((violations_total+1))
      pass=false
    fi
  done < "$f"
done
if [[ -s "$violations" ]]; then
  echo "----- Violations (operational scripts) -----"
  cat "$violations"
  echo "-------------------------------------------"
fi
rm -f "$violations"
echo "  ✅ Raw command scan completed"

echo "[CHECK] Ensuring executable bits for operational scripts..."
need_exec=false
for f in "${files[@]}"; do
  if [[ ! -x "$f" ]]; then
    echo "  ⚠️  Not executable: ${f#$ROOT_DIR/}"
    need_exec=true
  fi
done
if [[ "$need_exec" == "true" ]]; then
  echo "  ➜ Run:"
  echo "    chmod +x scripts/*.sh deploy_*.sh backend/*.sh"
else
  echo "  ✅ Executable bits look good"
fi

echo "[SUMMARY]"
echo "Scripts checked: $checked"
echo "Operational scripts skipped: $skipped"
echo "Violations found: $violations_total"

if [[ "$pass" == "true" ]]; then
  echo "[RESULT] ✅ SSH system validation passed."
  exit 0
else
  echo "[RESULT] ❌ SSH system validation failed."
  exit 1
fi


