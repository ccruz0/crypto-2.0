#!/usr/bin/env bash
# Scan staged changes only (not working tree).
# Block Telegram bot tokens and common secret-looking KEY=VALUE lines.
#
# Word-boundary match avoids false positives on names ending in _BOT plus KEN.
#
# Install (from repo root):
#   cp scripts/git-hooks/pre-commit-secret-scan.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#
# Or use a wrapper that runs: bash scripts/git-hooks/pre-commit-secret-scan.sh

set -euo pipefail

if git diff --cached -U0 | grep -E -n '^[+].*[0-9]{8,12}:[A-Za-z0-9_-]{30,}' >/dev/null; then
  echo "ERROR: Looks like a Telegram bot token is staged for commit." >&2
  echo "Remove/redact it, or move it into an ignored secrets file." >&2
  exit 1
fi

# Assemble TO+KEN so this file does not trip the scan when staged.
_TO=TO
_KEN=KEN
_KEYS="API_KEY|APISECRET|SECRET|${_TO}${_KEN}|PRIVATE_KEY"
if git diff --cached -U0 | grep -E -n "^[+].*\\b(${_KEYS})=" >/dev/null; then
  echo "ERROR: A secret-looking KEY=VALUE line is staged for commit." >&2
  echo "Move it into secrets/runtime.env (ignored) or redact it." >&2
  exit 1
fi

exit 0
