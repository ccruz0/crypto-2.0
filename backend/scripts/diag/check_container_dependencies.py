#!/usr/bin/env python3
"""Verify critical Python dependencies are installed in the container."""

import importlib
import sys

modules = [
    "pydantic",
    "pydantic_settings",
    "requests",
]

failed = []
for m in modules:
    try:
        importlib.import_module(m)
        print(f"{m}: OK")
    except Exception as e:
        print(f"{m}: FAILED -> {e}")
        failed.append(m)

sys.exit(1 if failed else 0)
