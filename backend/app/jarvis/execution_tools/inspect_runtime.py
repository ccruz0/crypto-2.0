"""Read-only runtime inspection tool."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


def inspect_runtime() -> dict[str, Any]:
    return {
        "tool": "inspect_runtime",
        "environment": os.environ.get("ENVIRONMENT", "unknown"),
        "runtime_origin": os.environ.get("RUNTIME_ORIGIN", "unknown"),
        "jarvis_enabled": os.environ.get("JARVIS_ENABLED", "false"),
        "jarvis_dry_run_only": os.environ.get("JARVIS_DRY_RUN_ONLY", "true"),
        "read_only": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
