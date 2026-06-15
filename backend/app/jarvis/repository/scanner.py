"""Read-only repository scanner for Jarvis Phase 4 knowledge graph."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services._paths import workspace_root

_SKIP_DIRS = frozenset(
    {".git", "node_modules", ".next", "__pycache__", ".archive", "proc", "sys", "dev", "run", ".venv", "venv"}
)
_ROUTE_PATTERN = re.compile(
    r'@(?:router|app)\.(?:get|post|put|patch|delete)\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_MODEL_PATTERN = re.compile(r"^class\s+(\w+)\(.*?(?:Base|Model)", re.MULTILINE)
_IMPORT_PATTERN = re.compile(r"^(?:from|import)\s+([\w.]+)", re.MULTILINE)
_TS_IMPORT_PATTERN = re.compile(r"""^import\s+.+from\s+['"]([^'"]+)['"]""", re.MULTILINE)
_WORKFLOW_PATTERN = re.compile(r"^name:\s*(.+)$", re.MULTILINE)
_DEPLOY_PATTERN = re.compile(
    r"(deploy|docker-compose|dockerfile|prod_frontend|Dockerfile)",
    re.IGNORECASE,
)
_BACKEND_PREFIXES = ("app/", "backend/app/")
_FRONTEND_PREFIX = "frontend/"
_TEST_PATH_MARKERS = ("/tests/", "/test_", "_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")


def _discover_monorepo_root(primary: Path) -> Path | None:
    """Find monorepo root (backend + frontend/.github siblings), not backend-only trees."""
    for candidate in [primary, *primary.parents]:
        if not candidate.is_dir():
            continue
        if not (candidate / "backend").is_dir():
            continue
        if (candidate / "frontend").is_dir() or (candidate / ".github").is_dir():
            return candidate
        if (candidate / "docker-compose.yml").is_file() and (candidate / "frontend").is_dir():
            return candidate
    return None


def _scan_roots() -> list[Path]:
    """Return ordered scan roots: primary workspace + optional JARVIS_REPO_INDEX_ROOTS."""
    roots: list[Path] = []
    seen: set[str] = set()

    primary = workspace_root().resolve()
    roots.append(primary)
    seen.add(str(primary))

    monorepo = _discover_monorepo_root(primary)
    if monorepo and str(monorepo) not in seen:
        roots.append(monorepo)
        seen.add(str(monorepo))

    extra = (os.environ.get("JARVIS_REPO_INDEX_ROOTS") or "").strip()
    for part in extra.split(","):
        part = part.strip()
        if not part:
            continue
        candidate = Path(part).resolve()
        key = str(candidate)
        if key in seen or not candidate.is_dir():
            continue
        seen.add(key)
        roots.append(candidate)
    return roots


def _iter_source_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo_root.rglob("*"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in {".py", ".ts", ".tsx", ".yml", ".yaml", ".sh", ".prisma"}:
            files.append(path)
    return files


def _relative(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _is_backend_python(rel: str) -> bool:
    norm = rel.replace("\\", "/")
    return any(norm.startswith(prefix) for prefix in _BACKEND_PREFIXES) or norm.startswith("app/")


def _is_frontend_source(rel: str) -> bool:
    norm = rel.replace("\\", "/")
    return norm.startswith(_FRONTEND_PREFIX) and norm.endswith((".ts", ".tsx"))


def _is_test_file(rel: str) -> bool:
    norm = rel.replace("\\", "/").lower()
    return any(marker in norm for marker in _TEST_PATH_MARKERS)


def _collect_files(roots: list[Path]) -> tuple[list[tuple[Path, Path]], dict[str, Any]]:
    """Gather source files from all scan roots, deduplicated by relative path."""
    files: list[tuple[Path, Path]] = []
    seen_paths: set[str] = set()
    root_meta: list[dict[str, str]] = []

    for root in roots:
        root_files = _iter_source_files(root)
        root_meta.append({"path": str(root), "file_count": str(len(root_files))})
        for path in root_files:
            rel = _relative(path, root)
            if rel in seen_paths:
                continue
            seen_paths.add(rel)
            files.append((path, root))

    return files, {"scan_roots": root_meta, "unique_file_count": len(files)}


def _scan_modules(file_entries: list[tuple[Path, Path]]) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    for path, root in file_entries:
        rel = _relative(path, root)
        if path.suffix == ".py" and _is_backend_python(rel):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            kind = "test" if _is_test_file(rel) else "python_module"
            modules.append(
                {
                    "path": rel,
                    "line_count": len(text.splitlines()),
                    "imports": _IMPORT_PATTERN.findall(text)[:20],
                    "kind": kind,
                }
            )
        elif path.suffix in {".ts", ".tsx"} and _is_frontend_source(rel):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            kind = "test" if _is_test_file(rel) else "frontend_module"
            modules.append(
                {
                    "path": rel,
                    "line_count": len(text.splitlines()),
                    "imports": _TS_IMPORT_PATTERN.findall(text)[:20],
                    "kind": kind,
                }
            )
    # Cap per kind so frontend/tests are not crowded out by backend volume.
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for mod in modules:
        by_kind.setdefault(mod.get("kind", "python_module"), []).append(mod)
    limits = {"python_module": 600, "frontend_module": 400, "test": 200}
    capped: list[dict[str, Any]] = []
    for kind, items in by_kind.items():
        capped.extend(items[: limits.get(kind, 300)])
    return capped


def _scan_api_endpoints(file_entries: list[tuple[Path, Path]]) -> list[dict[str, str]]:
    endpoints: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for path, root in file_entries:
        if path.suffix != ".py" or "routes" not in path.name:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = _relative(path, root)
        for match in _ROUTE_PATTERN.finditer(text):
            key = (match.group(1), rel)
            if key in seen:
                continue
            seen.add(key)
            endpoints.append({"path": match.group(1), "file": rel})
    return endpoints[:400]


def _scan_database_models(file_entries: list[tuple[Path, Path]]) -> list[dict[str, str]]:
    models: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for path, root in file_entries:
        if path.suffix not in {".py", ".prisma"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = _relative(path, root)
        if path.suffix == ".prisma":
            for match in re.finditer(r"^model\s+(\w+)\s*\{", text, re.MULTILINE):
                key = (match.group(1), rel)
                if key not in seen:
                    seen.add(key)
                    models.append({"name": match.group(1), "file": rel, "source": "prisma"})
        else:
            for match in _MODEL_PATTERN.finditer(text):
                key = (match.group(1), rel)
                if key not in seen:
                    seen.add(key)
                    models.append({"name": match.group(1), "file": rel, "source": "sqlalchemy"})
    return models[:300]


def _scan_workflows(roots: list[Path]) -> list[dict[str, str]]:
    workflows: list[dict[str, str]] = []
    seen: set[str] = set()
    for root in roots:
        wf_dir = root / ".github" / "workflows"
        if not wf_dir.is_dir():
            continue
        for path in sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml")):
            rel = _relative(path, root)
            if rel in seen:
                continue
            seen.add(rel)
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            name_match = _WORKFLOW_PATTERN.search(text)
            workflows.append(
                {
                    "file": rel,
                    "name": (name_match.group(1).strip() if name_match else path.stem),
                }
            )
    return workflows


def _scan_deployment_scripts(file_entries: list[tuple[Path, Path]]) -> list[dict[str, str]]:
    scripts: list[dict[str, str]] = []
    seen: set[str] = set()
    for path, root in file_entries:
        rel = _relative(path, root)
        name = path.name
        is_dockerfile = name.lower().startswith("dockerfile")
        is_compose = name.startswith("docker-compose") and path.suffix in {".yml", ".yaml"}
        if path.suffix not in {".sh", ".yml", ".yaml"} and not is_dockerfile:
            continue
        if not (is_dockerfile or is_compose or _DEPLOY_PATTERN.search(rel) or _DEPLOY_PATTERN.search(name)):
            continue
        if rel in seen:
            continue
        seen.add(rel)
        kind = "dockerfile" if is_dockerfile else "deployment_script"
        scripts.append({"path": rel, "kind": kind})
    return scripts[:150]


def _scan_scripts(file_entries: list[tuple[Path, Path]]) -> list[dict[str, str]]:
    """Index operational scripts under scripts/ and backend/scripts/."""
    scripts: list[dict[str, str]] = []
    seen: set[str] = set()
    for path, root in file_entries:
        rel = _relative(path, root)
        if path.suffix != ".sh" and not (path.suffix == ".py" and "/scripts/" in rel):
            continue
        if not (rel.startswith("scripts/") or rel.startswith("backend/scripts/")):
            continue
        if rel in seen:
            continue
        seen.add(rel)
        scripts.append({"path": rel, "kind": "script"})
    return scripts[:200]


def scan_repository(*, incremental: bool = False, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Scan repository and return structured metadata (read-only)."""
    roots = _scan_roots()
    file_entries, scan_info = _collect_files(roots)
    primary_root = roots[0]

    modules = _scan_modules(file_entries)
    report: dict[str, Any] = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(primary_root),
        "scan_roots": scan_info["scan_roots"],
        "file_count": scan_info["unique_file_count"],
        "modules": modules,
        "api_endpoints": _scan_api_endpoints(file_entries),
        "database_models": _scan_database_models(file_entries),
        "workflows": _scan_workflows(roots),
        "deployment_scripts": _scan_deployment_scripts(file_entries),
        "scripts": _scan_scripts(file_entries),
        "read_only": True,
        "incremental": incremental,
        "index_summary": {
            "backend_modules": sum(1 for m in modules if m.get("kind") == "python_module"),
            "frontend_modules": sum(1 for m in modules if m.get("kind") == "frontend_module"),
            "test_files": sum(1 for m in modules if m.get("kind") == "test"),
        },
    }
    if incremental and previous:
        prev_paths = {m.get("path") for m in previous.get("modules", []) if isinstance(m, dict)}
        new_modules = [m for m in report["modules"] if m.get("path") not in prev_paths]
        report["delta"] = {"new_modules": len(new_modules), "previous_scan": previous.get("scanned_at")}
    return report
