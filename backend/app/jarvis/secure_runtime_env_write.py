"""
Append or replace KEY=value in runtime.env without logging secret material.

Uses same container path convention as dashboard intake when RUNTIME_ENV_PATH unset.
"""

from __future__ import annotations

import errno
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

_DEFAULT_PATH = "/app/secrets/runtime.env"
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def runtime_env_path() -> str:
    return (os.getenv("RUNTIME_ENV_PATH") or _DEFAULT_PATH).strip()


def persist_env_var_value(env_var: str, value: str, *, path: str | None = None) -> None:
    """
    Write ``env_var=value`` into runtime.env (merge/replace line). Never logs ``value``.

    Raises:
        ValueError: invalid env var name, multiline value, or empty when disallowed.
    """
    key = (env_var or "").strip()
    if not key or not _KEY_RE.match(key):
        raise ValueError("invalid_env_var")
    raw = value if value is not None else ""
    if "\n" in raw or "\r" in raw:
        raise ValueError("invalid_value_multiline")
    val = raw.strip()
    if not val:
        raise ValueError("invalid_value_empty")

    p = Path(path or runtime_env_path())
    p.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if p.is_file():
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []

    prefix = f"{key}="
    new_lines: list[str] = []
    replaced = False
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            new_lines.append(line)
            continue
        if s.startswith(prefix) or s.split("=", 1)[0].strip() == key:
            if not replaced:
                new_lines.append(f"{key}={val}")
                replaced = True
            continue
        new_lines.append(line)
    if not replaced:
        new_lines.append(f"{key}={val}")

    text = "\n".join(new_lines) + "\n"
    tmp: str | None = None
    tmp_in_parent = False
    try:
        # Prefer temp file next to target (atomic os.replace). A file-only bind mount
        # for runtime.env often makes the parent dir non-writable for new files; fall
        # back to system temp. If replace from /tmp then fails (EXDEV, no rename into dir,
        # or permission), fall back to direct write (still updates the mounted file).
        try:
            fd, tmp = tempfile.mkstemp(prefix="runtime.", suffix=".env.tmp", dir=str(p.parent))
            tmp_in_parent = True
        except OSError:
            fd, tmp = tempfile.mkstemp(prefix="runtime.", suffix=".env.tmp", dir=tempfile.gettempdir())
        os.close(fd)
        Path(tmp).write_text(text, encoding="utf-8")
        try:
            os.replace(tmp, p)
        except OSError as exc:
            if tmp_in_parent:
                raise
            try:
                Path(tmp).unlink(missing_ok=True)
            except OSError:
                pass
            tmp = None
            if exc.errno in (errno.EXDEV, errno.EACCES, errno.EPERM):
                p.write_text(text, encoding="utf-8")
            else:
                raise
        else:
            tmp = None
    finally:
        if tmp:
            try:
                Path(tmp).unlink(missing_ok=True)
            except OSError:
                pass
    logger.info("jarvis.runtime_env.persisted env_var=%s path=%s", key, str(p))
