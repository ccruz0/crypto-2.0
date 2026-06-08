"""Filesystem + pytest helpers for Perico (phase 1: single repo root, path-confined)."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

_MAX_LIST_ENTRIES = 200
_MAX_READ_BYTES = 400_000
_MAX_GREP_FILES = 600
_MAX_GREP_MATCHES = 120


def perico_repo_root() -> Path:
    """
    Root directory for Perico repo-relative paths.

    - If ``PERICO_REPO_ROOT`` is set, it wins.
    - In backend-aws images, application code lives under ``/app`` (``COPY backend/ /app/``),
      not under host paths like ``/home/ubuntu/crypto-2.0``.
    - Local dev monorepo default remains ``/home/ubuntu/crypto-2.0`` when ``/app/app`` is absent.
    """
    raw = (os.getenv("PERICO_REPO_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    if Path("/app/app").is_dir():
        return Path("/app").resolve()
    return Path("/home/ubuntu/crypto-2.0").expanduser().resolve()


def perico_repo_runtime_ready() -> tuple[bool, str]:
    """
    Return (ok, operator_message_es). Used to fail-fast before Perico tool execution when
    the filesystem layout does not match what tools expect.
    """
    root = perico_repo_root()
    try:
        root = root.resolve()
    except OSError as exc:
        return False, f"No se pudo resolver PERICO_REPO_ROOT: {exc}"
    if not root.is_dir():
        return (
            False,
            "Perico: la raíz del repositorio no existe en este runtime "
            f"({root}). Define PERICO_REPO_ROOT al directorio que contiene el paquete `app/` "
            "(en contenedores suele ser /app).",
        )
    if (root / "app").is_dir():
        return True, ""
    if (root / "backend" / "app").is_dir():
        return True, ""
    return (
        False,
        f"Perico: en {root} no aparece el árbol `app/` ni `backend/app/`; "
        "revisa PERICO_REPO_ROOT o el despliegue del código.",
    )


def _perico_pytest_cwd() -> Path:
    root = perico_repo_root()
    backend = root / "backend"
    return backend if backend.is_dir() else root


def _perico_python_module_pytest_probe(python: str, cwd: Path) -> bool:
    try:
        proc = subprocess.run(
            [python, "-m", "pytest", "--version"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception:
        return False
    return proc.returncode == 0


def _perico_binary_runs(cmd: list[str], cwd: Path) -> bool:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception:
        return False
    return proc.returncode == 0


def perico_resolve_pytest_command(cwd: Path | None = None) -> tuple[list[str], str]:
    """
    Autonomously detect a working pytest invocation for this runtime.

    Search order (first that answers ``--version`` wins):

    1. ``$PERICO_TEST_COMMAND`` — full shell-style override (``pytest -q`` etc.).
    2. ``$PERICO_PYTHON`` — ``[$PERICO_PYTHON, -m, pytest]`` if its ``-m pytest`` probe passes.
    3. Repo-local virtualenvs: ``.venv-test-runner``, ``.venv``, ``venv`` via ``python -m pytest``.
    4. Repo-local binaries: ``.venv-test-runner/bin/pytest``, ``.venv/bin/pytest``, ``venv/bin/pytest``.
    5. ``poetry run python -m pytest`` when a ``pyproject.toml`` mentions ``[tool.poetry]``.
    6. ``tox -q`` when ``tox.ini`` exists.
    7. ``python3 -m pytest`` as last resort.

    Returns ``(cmd_prefix, source_label)``. ``source_label`` is a short tag like
    ``env_override``, ``venv-test-runner``, ``system_python`` used by UX and deliverables.
    """
    search_cwd = cwd or _perico_pytest_cwd()
    root = perico_repo_root()

    override = (os.environ.get("PERICO_TEST_COMMAND") or "").strip()
    if override:
        parts = override.split()
        if parts:
            return parts, "env_override"

    py_explicit = (os.environ.get("PERICO_PYTHON") or "").strip()
    if py_explicit and _perico_python_module_pytest_probe(py_explicit, search_cwd):
        return [py_explicit, "-m", "pytest"], "perico_python"

    venv_names = (".venv-test-runner", ".venv", "venv")
    for base in (root, search_cwd):
        for name in venv_names:
            py_path = base / name / "bin" / "python"
            if py_path.exists() and _perico_python_module_pytest_probe(str(py_path), search_cwd):
                return [str(py_path), "-m", "pytest"], name

    for base in (root, search_cwd):
        for name in venv_names:
            bin_path = base / name / "bin" / "pytest"
            if bin_path.exists() and _perico_binary_runs([str(bin_path), "--version"], search_cwd):
                return [str(bin_path)], f"{name}-bin"

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            blob = pyproject.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            blob = ""
        if "[tool.poetry]" in blob and _perico_binary_runs(
            ["poetry", "run", "python", "-m", "pytest", "--version"], search_cwd
        ):
            return ["poetry", "run", "python", "-m", "pytest"], "poetry"

    tox_ini = root / "tox.ini"
    if tox_ini.is_file() and _perico_binary_runs(["tox", "--version"], search_cwd):
        return ["tox", "-q"], "tox"

    if _perico_python_module_pytest_probe("python3", search_cwd):
        return ["python3", "-m", "pytest"], "system_python"

    return ["python3", "-m", "pytest"], "unavailable"


def perico_verify_pytest_cwd() -> tuple[bool, str]:
    """
    Cheap sanity check that a usable pytest runner can start from the same cwd ``perico_run_pytest`` uses.
    """
    cwd = _perico_pytest_cwd()
    if not cwd.is_dir():
        return False, f"Perico: el directorio de trabajo para pytest no existe ({cwd})."
    cmd, source = perico_resolve_pytest_command(cwd=cwd)
    if source == "unavailable":
        return False, (
            f"Perico: no se encontró un runner de pytest utilizable en {cwd}. "
            "Probé: $PERICO_TEST_COMMAND, $PERICO_PYTHON, .venv-test-runner, .venv, venv, poetry, tox, python3 -m pytest."
        )
    try:
        proc = subprocess.run(
            [*cmd, "--version"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"Perico: timeout al comprobar pytest en {cwd}."
    except Exception as exc:
        return False, f"Perico: no se pudo invocar pytest en {cwd}: {exc}"
    if proc.returncode != 0:
        tail = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()[-800:]
        return (
            False,
            f"Perico: `{' '.join(cmd)} --version` falló en {cwd} (código {proc.returncode}, origen={source}). {tail}",
        )
    return True, ""


def perico_verify_pytest_relative_target(relative_path: str) -> tuple[bool, str]:
    """
    When a concrete test path is planned, ensure it exists somewhere ``perico_run_pytest`` can target.

    Accepts repo-root paths (``backend/tests/foo.py``), or paths relative to the pytest cwd
    (often ``tests/foo.py`` when ``cwd`` is ``<root>/backend``).
    """
    rel = (relative_path or "").strip().replace("\\", "/")
    if not rel:
        return True, ""
    root = perico_repo_root().resolve()
    cwd = _perico_pytest_cwd().resolve()
    candidates: list[Path] = []
    try:
        candidates.append(_safe_child(rel))
    except Exception as exc:
        return False, f"Perico: ruta de tests no permitida ({relative_path!r}): {exc}"
    if not rel.startswith("backend/") and (root / "backend").is_dir():
        try:
            candidates.append(_safe_child(f"backend/{rel}"))
        except Exception:
            pass
    try:
        p_cwd = (cwd / rel).resolve()
        p_cwd.relative_to(root)
        candidates.append(p_cwd)
    except Exception:
        pass
    for p in candidates:
        if p.exists():
            return True, ""
    return (
        False,
        f"Perico: la ruta de tests {relative_path!r} no existe bajo la raíz del repo ({root}).",
    )


def perico_shallow_runtime_dir_hint() -> str:
    """
    Short, bounded directory hints for operators (no recursive walks).

    Helps when ``PERICO_REPO_ROOT`` apunta a una ruta inexistente en contenedor.
    """
    parts: list[str] = []
    for label, base in ((" /app", Path("/app")), (" repo_root", perico_repo_root())):
        try:
            b = base.resolve()
        except OSError:
            continue
        if not b.is_dir():
            parts.append(f"{label.strip()}={b} (no existe)")
            continue
        try:
            names = sorted(p.name for p in b.iterdir() if p.is_dir())[:10]
            if names:
                parts.append(f"{label.strip()} {b}: {', '.join(names)}")
            else:
                parts.append(f"{label.strip()} {b}: (sin subcarpetas)")
        except OSError as exc:
            parts.append(f"{label.strip()} {b}: ({exc})")
    return " | ".join(parts)[:500]


def _safe_child(rel: str) -> Path:
    rel_norm = (rel or ".").strip().replace("\\", "/").lstrip("/")
    if ".." in Path(rel_norm).parts:
        raise ValueError("relative_path must not contain '..'")
    root = perico_repo_root()
    full = (root / rel_norm).resolve()
    full.relative_to(root)
    return full


def perico_repo_read(
    *,
    operation: str,
    relative_path: str = "",
    pattern: str = "",
    max_results: int = 80,
) -> dict[str, Any]:
    """
    operation: list | read | grep
    - list: directory listing under relative_path (default ".")
    - read: file contents (text), truncated
    - grep: simple substring search under relative_path directory tree (Python walk)
    """
    op = (operation or "").strip().lower()
    if op not in ("list", "read", "grep"):
        return {"ok": False, "error": "invalid_operation", "allowed": ["list", "read", "grep"]}

    try:
        base = _safe_child(relative_path or ".")
    except Exception as e:
        return {"ok": False, "error": "path_not_allowed", "detail": str(e)}

    if op == "list":
        if not base.is_dir():
            return {"ok": False, "error": "not_a_directory", "path": str(base)}
        entries: list[str] = []
        try:
            for p in sorted(base.iterdir(), key=lambda x: x.name.lower()):
                suffix = "/" if p.is_dir() else ""
                entries.append(f"{p.name}{suffix}")
                if len(entries) >= _MAX_LIST_ENTRIES:
                    break
        except OSError as e:
            return {"ok": False, "error": "list_failed", "detail": str(e)}
        return {"ok": True, "operation": "list", "path": str(base), "entries": entries}

    if op == "read":
        if not base.is_file():
            return {"ok": False, "error": "not_a_file", "path": str(base)}
        try:
            raw = base.read_bytes()[:_MAX_READ_BYTES]
        except OSError as e:
            return {"ok": False, "error": "read_failed", "detail": str(e)}
        text = raw.decode("utf-8", errors="replace")
        truncated = base.stat().st_size > len(raw)
        return {
            "ok": True,
            "operation": "read",
            "path": str(base),
            "content": text,
            "truncated": truncated,
            "size_bytes": base.stat().st_size,
        }

    # grep
    if not base.exists():
        return {"ok": False, "error": "path_missing", "path": str(base)}
    needle = (pattern or "").strip()
    if len(needle) < 2:
        return {"ok": False, "error": "pattern_too_short", "min_chars": 2}
    lim = max(1, min(int(max_results or 80), _MAX_GREP_MATCHES))
    matches: list[dict[str, Any]] = []
    files_seen = 0
    try:
        pat = re.compile(re.escape(needle), re.IGNORECASE)
    except re.error as e:
        return {"ok": False, "error": "invalid_pattern", "detail": str(e)}

    def _grep_file(fp: Path) -> None:
        nonlocal files_seen, matches
        if len(matches) >= lim or files_seen > _MAX_GREP_FILES:
            return
        if fp.suffix.lower() not in (
            ".py",
            ".md",
            ".txt",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".sh",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".css",
            ".html",
        ):
            return
        files_seen += 1
        try:
            data = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return
        for i, line in enumerate(data.splitlines(), start=1):
            if pat.search(line):
                rel = str(fp.relative_to(perico_repo_root()))
                matches.append({"path": rel, "line": i, "text": line[:500]})
                if len(matches) >= lim:
                    return

    if base.is_file():
        _grep_file(base)
    else:
        for root, _, files in os.walk(base, topdown=True):
            for fn in sorted(files):
                _grep_file(Path(root) / fn)
                if len(matches) >= lim or files_seen > _MAX_GREP_FILES:
                    break
            if len(matches) >= lim or files_seen > _MAX_GREP_FILES:
                break
    return {
        "ok": True,
        "operation": "grep",
        "base": str(base),
        "pattern": needle,
        "matches": matches,
        "files_scanned": files_seen,
        "truncated": len(matches) >= lim,
    }


def perico_apply_patch(
    *,
    relative_path: str,
    old_text: str,
    new_text: str = "",
) -> dict[str, Any]:
    """
    Single-file single-occurrence replace. old_text must match exactly once.
    Guarded by PERICO_WRITE_ENABLED=1.
    """
    if (os.getenv("PERICO_WRITE_ENABLED") or "").strip().lower() not in ("1", "true", "yes", "on"):
        return {
            "ok": False,
            "error": "writes_disabled",
            "message": "Set PERICO_WRITE_ENABLED=1 to allow perico_apply_patch (dev/lab only).",
        }
    if not (relative_path or "").strip():
        return {"ok": False, "error": "missing_relative_path"}
    old = old_text or ""
    if not old.strip():
        return {"ok": False, "error": "missing_old_text"}
    try:
        path = _safe_child(relative_path)
    except Exception as e:
        return {"ok": False, "error": "path_not_allowed", "detail": str(e)}
    if not path.is_file():
        return {"ok": False, "error": "not_a_file", "path": str(path)}
    try:
        before = path.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return {"ok": False, "error": "not_utf8_text", "path": str(path)}
    except OSError as e:
        return {"ok": False, "error": "read_failed", "detail": str(e)}
    count = before.count(old)
    if count == 0:
        return {"ok": False, "error": "old_text_not_found", "path": str(path)}
    if count > 1:
        return {"ok": False, "error": "old_text_not_unique", "occurrences": count, "path": str(path)}
    after = before.replace(old, new_text, 1)
    try:
        path.write_text(after, encoding="utf-8", newline="\n")
    except OSError as e:
        return {"ok": False, "error": "write_failed", "detail": str(e)}
    return {
        "ok": True,
        "path": str(path),
        "relative_path": relative_path.strip(),
        "diff_preview": f"--- before (trunc)\n{before[:800]}\n+++ after (trunc)\n{after[:800]}",
        "bytes_written": len(after.encode("utf-8")),
    }


def perico_run_pytest(
    *,
    relative_path: str = "",
    extra_args: str = "",
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    """
    Run ``python3 -m pytest`` with cwd = repo backend/ (or repo root if backend missing).
    """
    root = perico_repo_root()
    backend = root / "backend"
    cwd = backend if backend.is_dir() else root
    timeout = max(15, min(int(timeout_seconds or 180), 900))
    cmd_prefix, runner_source = perico_resolve_pytest_command(cwd=cwd)
    if runner_source == "unavailable":
        return {
            "ok": False,
            "error": "pytest_runner_unavailable",
            "cwd": str(cwd),
            "detail": (
                "Perico no encontró un runner de pytest en este runtime "
                "(probé: $PERICO_TEST_COMMAND, $PERICO_PYTHON, .venv-test-runner, .venv, venv, poetry, tox, python3 -m pytest)."
            ),
        }
    cmd = [*cmd_prefix, "-q", "--tb=no"]
    tail = (relative_path or "").strip()
    if tail:
        try:
            _safe_child(tail)  # ensure path stays in repo
        except Exception as e:
            return {"ok": False, "error": "path_not_allowed", "detail": str(e)}
        cmd.append(tail)
    extra = (extra_args or "").strip()
    if extra:
        cmd.extend(extra.split())
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "timeout",
            "timeout_seconds": timeout,
            "cmd": cmd,
            "cwd": str(cwd),
            "runner_source": runner_source,
        }
    except Exception as e:
        return {"ok": False, "error": "spawn_failed", "detail": str(e), "runner_source": runner_source}
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    passed = proc.returncode == 0
    summary = _parse_pytest_cli_summary(proc.stdout or "", proc.stderr or "")
    return {
        "ok": True,
        "pytest": True,
        "tests_ok": passed,
        "exit_code": proc.returncode,
        "tests_total": summary.get("tests_total"),
        "tests_failed": summary.get("tests_failed"),
        "tests_passed": summary.get("tests_passed"),
        "key_error_summary": summary.get("key_error_summary") or "",
        "stdout_tail": (proc.stdout or "")[-8000:],
        "stderr_tail": (proc.stderr or "")[-8000:],
        "combined_tail": out[-12_000:],
        "cwd": str(cwd),
        "cmd": cmd,
        "runner_source": runner_source,
    }


def _parse_pytest_cli_summary(stdout: str, stderr: str) -> dict[str, Any]:
    """Best-effort counts + short error line from pytest -q text output."""
    blob = f"{stdout}\n{stderr}"
    tests_passed = None
    tests_failed = None
    for m in re.finditer(r"(\d+)\s+passed", blob):
        try:
            tests_passed = int(m.group(1))
        except ValueError:
            pass
    for m in re.finditer(r"(\d+)\s+failed", blob):
        try:
            tests_failed = int(m.group(1))
        except ValueError:
            pass
    total = None
    if tests_passed is not None or tests_failed is not None:
        total = (tests_passed or 0) + (tests_failed or 0)
    key_err = ""
    for line in (stderr or "").splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if any(x in low for x in ("error", "failed", "assert", "e   ")):
            key_err = s[:500]
            break
    if not key_err and tests_failed and tests_failed > 0:
        for line in reversed((stdout or "").splitlines()[-40:]):
            t = line.strip()
            if t and ("FAILED" in t or "Error" in t or "AssertionError" in t):
                key_err = t[:500]
                break
    return {
        "tests_total": total,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "key_error_summary": key_err,
    }
