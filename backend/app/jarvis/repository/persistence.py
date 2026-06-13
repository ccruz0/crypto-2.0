"""Persist repository metadata for incremental refresh."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.jarvis.repository.graph import build_repository_graph
from app.jarvis.repository.scanner import scan_repository

_METADATA_DIR = Path(__file__).resolve().parent / "data"
_METADATA_FILE = _METADATA_DIR / "repository_metadata.json"


def _ensure_dir() -> Path:
    _METADATA_DIR.mkdir(parents=True, exist_ok=True)
    return _METADATA_DIR


def save_repository_metadata(report: dict[str, Any]) -> dict[str, Any]:
    _ensure_dir()
    graph = build_repository_graph(report)
    payload = {
        "report": report,
        "graph": graph.to_dict(),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    _METADATA_FILE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


def get_repository_metadata() -> dict[str, Any] | None:
    if not _METADATA_FILE.is_file():
        return None
    try:
        return json.loads(_METADATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def refresh_repository_metadata(*, incremental: bool = True) -> dict[str, Any]:
    previous = get_repository_metadata()
    prev_report = (previous or {}).get("report") if incremental else None
    report = scan_repository(incremental=incremental, previous=prev_report)
    return save_repository_metadata(report)
