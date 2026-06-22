"""Guard: the disk investigator must not import any trading/signal-monitor module.

Static (AST) check of the investigator source files, so the assertion holds even
if those modules are never imported at runtime in a given test.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Substrings that indicate a trading / signal-monitor coupling we must never have.
_FORBIDDEN = (
    "signal_monitor",
    "trading_guardrails",
    "trading",
    "exchange_sync",
    "order_executor",
    "place_order",
)

_FILES = (
    "app/jarvis/investigations/investigators/disk_pressure.py",
    "app/jarvis/investigations/investigators/disk_evidence.py",
)


def _imported_modules(source: str) -> list[str]:
    tree = ast.parse(source)
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.append(node.module)
    return mods


def _backend_root() -> Path:
    # tests/ lives directly under backend/
    return Path(__file__).resolve().parent.parent


def test_disk_investigator_imports_no_trading_or_signal_modules():
    root = _backend_root()
    offenders: list[str] = []
    for rel in _FILES:
        source = (root / rel).read_text(encoding="utf-8")
        for mod in _imported_modules(source):
            lowered = mod.lower()
            if any(bad in lowered for bad in _FORBIDDEN):
                offenders.append(f"{rel} imports {mod}")
    assert not offenders, f"forbidden imports found: {offenders}"
