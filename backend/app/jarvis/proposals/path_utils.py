"""Path helpers for Phase 4B proposal patch generation."""

from __future__ import annotations

from pathlib import Path


def resolve_repo_file(repo_root: Path, rel_path: str) -> Path | None:
    """Resolve a template-relative file path against the workspace layout."""
    rel = rel_path.replace("\\", "/").lstrip("/")
    candidates: list[Path] = [repo_root / rel]
    if rel.startswith("backend/"):
        stripped = rel[len("backend/") :]
        candidates.append(repo_root / stripped)
    if (repo_root / "backend").is_dir():
        candidates.append(repo_root / "backend" / rel.removeprefix("backend/"))
    if rel.startswith("frontend/") and (repo_root / "app").is_dir():
        candidates.append(repo_root.parent / rel)
    for path in candidates:
        if path.is_file():
            return path
    return None


def is_backend_workspace(repo_root: Path) -> bool:
    """True when repo_root is the backend package root (contains app/, not backend/app/)."""
    return (repo_root / "app").is_dir() and not (repo_root / "backend" / "app").is_dir()


def rewrite_patch_paths_for_workspace(patch_content: str, repo_root: Path) -> str:
    """Rewrite unified diff paths when the workspace root is backend/ instead of monorepo root."""
    if not is_backend_workspace(repo_root):
        return patch_content

    rewritten: list[str] = []
    for line in patch_content.splitlines(keepends=True):
        if line.startswith("diff --git a/backend/"):
            line = line.replace("diff --git a/backend/", "diff --git a/", 1)
            line = line.replace(" b/backend/", " b/", 1)
        elif line.startswith("--- a/backend/"):
            line = line.replace("--- a/backend/", "--- a/", 1)
        elif line.startswith("+++ b/backend/"):
            line = line.replace("+++ b/backend/", "+++ b/", 1)
        rewritten.append(line)
    return "".join(rewritten)


def resolve_test_path(repo_root: Path, rel_path: str) -> Path | None:
    """Resolve a test file path for sandbox pytest invocation."""
    resolved = resolve_repo_file(repo_root, rel_path)
    return resolved
