#!/usr/bin/env python3
"""
Backfill incomplete .sections.json from corresponding .md files.

Run from backend/: PYTHONPATH=. python scripts/backfill_sections_json.py [--write]

Scans docs/agents/bug-investigations, telegram-alerts, execution-state,
generated-notes, and docs/runbooks/triage. For each .sections.json that is
incomplete (missing Root Cause, Recommended Fix, Affected Files, Task Summary),
parses the matching .md file and regenerates the sidecar.

Use --write to actually update files; without it, only reports what would be done.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _parse_all_markdown_sections(text: str) -> dict[str, str]:
    """Extract ALL ## Section Name -> content. Mirrors openclaw_client.parse_all_markdown_sections."""
    result: dict[str, str] = {}
    parts = text.split("---")
    if len(parts) >= 3:
        body = parts[2].strip()  # YAML frontmatter: ---...---\ncontent
    elif len(parts) == 2:
        # Single ---: pick the part with more ## sections (main content vs header/footer)
        body = max(parts, key=lambda p: p.count("\n## ")).strip()
    else:
        body = (parts[0] if parts else "").strip()
    if not body:
        return result
    pattern = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(body))
    if matches:
        preamble = body[: matches[0].start()].strip()
        if preamble:
            result["_preamble"] = preamble
    for idx, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        content = body[start:end].strip()
        if content and name.lower() not in ("", "n/a"):
            result[name] = content
    return result


def _repo_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    if (root / "app").is_dir():
        return root
    # When run from project root
    backend = Path.cwd() / "backend"
    if (backend / "app").is_dir():
        return backend
    return root


_REQUIRED_KEYS = ("Task Summary", "Root Cause", "Recommended Fix", "Affected Files")


def _is_incomplete(sections: dict) -> bool:
    """True if sidecar lacks structured content needed for deploy approval."""
    if not sections:
        return True
    has_any = any(
        sections.get(k) and str(sections.get(k)).strip().lower() not in ("", "n/a")
        for k in _REQUIRED_KEYS
    )
    return not has_any


def _search_dirs(root: Path) -> list[Path]:
    return [
        root / "docs" / "agents" / "bug-investigations",
        root / "docs" / "agents" / "telegram-alerts",
        root / "docs" / "agents" / "execution-state",
        root / "docs" / "agents" / "generated-notes",
        root / "docs" / "runbooks" / "triage",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill incomplete .sections.json from .md")
    parser.add_argument("--write", action="store_true", help="Actually write updated sidecars")
    args = parser.parse_args()
    dry_run = not args.write

    root = _repo_root()
    # docs/ is at project root; when run from backend/, root is backend/
    project_root = root.parent if (root / "app").is_dir() else root
    if not (project_root / "docs").is_dir():
        print("ERROR: docs/ not found. Run from backend/ or project root.")
        return 1

    updated = 0
    skipped = 0
    errors = 0

    for d in _search_dirs(project_root):
        if not d.is_dir():
            continue
        for sidecar in d.glob("*.sections.json"):
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
                sections = data.get("sections") or {}
                if not _is_incomplete(sections):
                    skipped += 1
                    continue

                # Infer .md path from sidecar name (e.g. notion-bug-{id}.sections.json -> notion-bug-{id}.md)
                md_path = sidecar.parent / sidecar.name.replace(".sections.json", ".md")
                if not md_path.exists():
                    print(f"SKIP {sidecar.name}: no matching .md")
                    errors += 1
                    continue

                raw = md_path.read_text(encoding="utf-8")
                parsed = _parse_all_markdown_sections(raw)
                if not parsed:
                    print(f"SKIP {sidecar.name}: no ## sections in .md")
                    errors += 1
                    continue

                if dry_run:
                    print(f"WOULD UPDATE {sidecar.relative_to(project_root)}: {len(parsed)} sections")
                    updated += 1
                else:
                    data["sections"] = parsed
                    data["source"] = data.get("source", "openclaw") + "+backfill"
                    sidecar.write_text(
                        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
                    print(f"UPDATED {sidecar.relative_to(project_root)}: {len(parsed)} sections")
                    updated += 1
            except Exception as e:
                print(f"ERROR {sidecar}: {e}")
                errors += 1

    print(f"\nDone: {updated} {'would be ' if dry_run else ''}updated, {skipped} already complete, {errors} errors")
    if dry_run and updated:
        print("Run with --write to apply changes.")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
