#!/usr/bin/env python3
"""Fail if a live-looking GitHub token is committed to the repository.

This guard exists to prevent inline GitHub tokens (e.g. ``gho_``/``ghp_``)
from being committed in env files, scripts, or docs. It scans git-tracked
files only and uses an entropy + length heuristic so that documented
placeholders and short test fixtures (e.g. ``ghp_test123``) do not trip it.

The full token value is NEVER printed; matches are reported redacted.

Exit code 0 = clean, 1 = a live-looking token was found, 2 = usage error.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# GitHub token prefixes (classic PAT, OAuth, server-to-server, refresh,
# fine-grained PAT). See GitHub token format docs.
TOKEN_RE = re.compile(r"\b(gho_|ghp_|ghs_|ghr_|github_pat_)([A-Za-z0-9_]+)")

# A real GitHub token has a long, high-entropy suffix. Documented placeholders
# and test fixtures are short and/or low-entropy (few distinct characters).
MIN_SUFFIX_LEN = 30
MIN_DISTINCT_CHARS = 20

# Directories/files that never contain real secrets and are safe to skip.
SKIP_PREFIXES = (
    ".git/",
    "node_modules/",
    "frontend/.next/",
)


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [p for p in out.stdout.split("\0") if p]


def looks_live(suffix: str) -> bool:
    return len(suffix) >= MIN_SUFFIX_LEN and len(set(suffix)) >= MIN_DISTINCT_CHARS


def redact(prefix: str, suffix: str) -> str:
    return f"{prefix}<REDACTED len={len(suffix)}>"


def scan() -> int:
    root = repo_root()
    findings: list[str] = []
    for rel in tracked_files(root):
        if any(rel.startswith(p) for p in SKIP_PREFIXES):
            continue
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError):
            continue
        if "gh" not in text and "github_pat_" not in text:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in TOKEN_RE.finditer(line):
                prefix, suffix = m.group(1), m.group(2)
                if looks_live(suffix):
                    findings.append(f"{rel}:{lineno}: {redact(prefix, suffix)}")

    if findings:
        print("ERROR: live-looking GitHub token(s) found in tracked files:", file=sys.stderr)
        for f in findings:
            print(f"  {f}", file=sys.stderr)
        print(
            "\nRemove the secret, source it from a secret store (e.g. AWS SSM), "
            "and rotate the exposed token in GitHub.",
            file=sys.stderr,
        )
        return 1

    print("OK: no live-looking GitHub tokens found in tracked files.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(scan())
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: git command failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
