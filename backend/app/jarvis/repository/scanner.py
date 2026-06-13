"""Read-only repository scanner for Jarvis Phase 4 knowledge graph."""

from __future__ import annotations

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
_WORKFLOW_PATTERN = re.compile(r"^name:\s*(.+)$", re.MULTILINE)
_DEPLOY_PATTERN = re.compile(r"(deploy|docker-compose|prod_frontend)", re.IGNORECASE)


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
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def _scan_modules(files: list[Path], repo_root: Path) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    for path in files:
        if path.suffix != ".py":
            continue
        rel = _relative(path, repo_root)
        if "/jarvis/" in rel or rel.startswith("backend/app/"):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            imports = _IMPORT_PATTERN.findall(text)[:20]
            modules.append(
                {
                    "path": rel,
                    "line_count": len(text.splitlines()),
                    "imports": imports,
                    "kind": "python_module",
                }
            )
    return modules[:200]


def _scan_api_endpoints(files: list[Path], repo_root: Path) -> list[dict[str, str]]:
    endpoints: list[dict[str, str]] = []
    for path in files:
        if path.suffix != ".py" or "routes" not in path.name:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in _ROUTE_PATTERN.finditer(text):
            endpoints.append({"path": match.group(1), "file": _relative(path, repo_root)})
    return endpoints[:300]


def _scan_database_models(files: list[Path], repo_root: Path) -> list[dict[str, str]]:
    models: list[dict[str, str]] = []
    for path in files:
        if path.suffix not in {".py", ".prisma"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if path.suffix == ".prisma":
            for match in re.finditer(r"^model\s+(\w+)\s*\{", text, re.MULTILINE):
                models.append({"name": match.group(1), "file": _relative(path, repo_root), "source": "prisma"})
        else:
            for match in _MODEL_PATTERN.finditer(text):
                models.append({"name": match.group(1), "file": _relative(path, repo_root), "source": "sqlalchemy"})
    return models[:200]


def _scan_workflows(repo_root: Path) -> list[dict[str, str]]:
    workflows: list[dict[str, str]] = []
    wf_dir = repo_root / ".github" / "workflows"
    if not wf_dir.is_dir():
        return workflows
    for path in wf_dir.glob("*.yml"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        name_match = _WORKFLOW_PATTERN.search(text)
        workflows.append(
            {
                "file": _relative(path, repo_root),
                "name": (name_match.group(1).strip() if name_match else path.stem),
            }
        )
    return workflows


def _scan_deployment_scripts(files: list[Path], repo_root: Path) -> list[dict[str, str]]:
    scripts: list[dict[str, str]] = []
    for path in files:
        rel = _relative(path, repo_root)
        if path.suffix not in {".sh", ".yml", ".yaml"}:
            continue
        if not _DEPLOY_PATTERN.search(rel) and not _DEPLOY_PATTERN.search(path.name):
            continue
        scripts.append({"path": rel, "kind": "deployment_script"})
    return scripts[:100]


def scan_repository(*, incremental: bool = False, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Scan repository and return structured metadata (read-only)."""
    repo_root = workspace_root()
    files = _iter_source_files(repo_root)
    report: dict[str, Any] = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "file_count": len(files),
        "modules": _scan_modules(files, repo_root),
        "api_endpoints": _scan_api_endpoints(files, repo_root),
        "database_models": _scan_database_models(files, repo_root),
        "workflows": _scan_workflows(repo_root),
        "deployment_scripts": _scan_deployment_scripts(files, repo_root),
        "read_only": True,
        "incremental": incremental,
    }
    if incremental and previous:
        prev_paths = {m.get("path") for m in previous.get("modules", []) if isinstance(m, dict)}
        new_modules = [m for m in report["modules"] if m.get("path") not in prev_paths]
        report["delta"] = {"new_modules": len(new_modules), "previous_scan": previous.get("scanned_at")}
    return report
