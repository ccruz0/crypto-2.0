"""
Cursor Execution Bridge — Phases 1–4: Staging, CLI, diff, tests, ingestion, PR.

Provisions an isolated writable copy of ATP, invokes Cursor CLI with the handoff
prompt in non-interactive mode, captures diff, runs tests, ingests results into
Notion, and optionally creates a PR. ATP source remains read-only.

Env vars:
  ATP_STAGING_ROOT       — Staging directory root (default: /tmp/atp-staging)
  CURSOR_CLI_PATH       — Cursor binary (default: cursor)
  CURSOR_AGENT_PATH     — Optional explicit path to cursor-agent (must be executable by the process user)
  CURSOR_BRIDGE_ENABLED — Master switch (default: false)
  CURSOR_CLI_TIMEOUT    — Timeout seconds for Cursor (default: 300)
  CURSOR_BRIDGE_TEST_TIMEOUT — Timeout per test suite (default: 120)
  CURSOR_BRIDGE_REQUIRE_APPROVAL — When true (default), API/scheduler require a patch_approved
      activity event before running; Telegram "Run Cursor Bridge" bypasses (human already approved).
  CURSOR_BRIDGE_AUTO_IN_ADVANCE — When true, scheduler auto-runs the bridge when eligible.
      When unset or false, no scheduler auto-run (production default); use Telegram or API.
  GITHUB_TOKEN          — For PR creation (requires repo scope)
  GITHUB_REPOSITORY     — owner/repo (default: ccruz0/crypto-2.0)

LAB vs staging writes:
  Persisted artifacts under the ATP workspace ``docs/`` (e.g. ``capture_diff`` → ``docs/agents/patches/``)
  use ``path_guard`` so OpenClaw/LAB policy applies. Git/Cursor/pytest/npm subprocess calls run in the
  **staging** tree only (``ATP_STAGING_ROOT``); they are not a substitute for guarded writes into ``docs/``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import subprocess
from collections import deque
from pathlib import Path
from typing import Any, Iterator

import httpx

try:
    import fcntl

    _HAS_FCNTL = True
except ImportError:  # Windows (non-production)
    fcntl = None  # type: ignore[assignment]
    _HAS_FCNTL = False

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_DEFAULT_REPO = "ccruz0/crypto-2.0"

_DEFAULT_STAGING_ROOT = "/tmp/atp-staging"
_DEFAULT_CURSOR_CLI = "cursor"
_DEFAULT_TIMEOUT = 300
_DEFAULT_TEST_TIMEOUT = 120
_MAX_STAGING_DIRS = 5
_PATCHES_SUBDIR = "docs/agents/patches"
# Keep in sync with app.services.agent_activity_log
_AGENT_ACTIVITY_LOG_DIR = "logs"
_AGENT_ACTIVITY_LOG_FILE = "agent_activity.jsonl"


def _workspace_root() -> Path:
    from app.services._paths import workspace_root
    return workspace_root()


def _handoffs_dir_for_bridge() -> Path:
    """Writable cursor-handoffs directory (must match ``save_cursor_handoff``)."""
    from app.services._paths import get_writable_cursor_handoffs_dir
    return get_writable_cursor_handoffs_dir()


@contextlib.contextmanager
def _cursor_bridge_phase2_lock(task_id: str) -> Iterator[bool]:
    """
    Serialize Cursor bridge phase-2 runs per task_id across gunicorn workers (fcntl file lock).

    Yields True if the lock was acquired (or lock skipped); False if another process already
    holds the lock (non-blocking). Only OSError from open/flock here is handled — errors from
    the ``with`` body must not be caught as lock failures (PermissionError is OSError).
    """
    if not _HAS_FCNTL or fcntl is None:
        yield True
        return

    tid = (task_id or "").strip()
    lock_root = Path((os.environ.get("CURSOR_BRIDGE_LOCK_DIR") or "").strip() or "/tmp/cursor-bridge-locks")
    try:
        lock_root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("cursor_bridge: lock dir mkdir failed %s: %s", lock_root, e)
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", tid)[:120] if tid else "unknown"
    lock_path = lock_root / f"{safe}.lock"
    f = None
    acquired = False
    duplicate = False

    try:
        f = open(lock_path, "a+", encoding="utf-8")
    except OSError as e:
        logger.warning("cursor_bridge: lock open failed task_id=%s: %s", tid, e)
        yield True
        return

    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
    except BlockingIOError:
        logger.info(
            "CursorBridge: concurrent run skipped (lock held) task_id=%s lock=%s",
            tid,
            lock_path,
        )
        duplicate = True
    except OSError as e:
        logger.warning("cursor_bridge: lock flock failed task_id=%s: %s", tid, e)

    if duplicate:
        try:
            f.close()
        except OSError:
            pass
        yield False
        return

    try:
        yield True
    finally:
        if acquired and f is not None:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        if f is not None:
            try:
                f.close()
            except OSError:
                pass


def _staging_root() -> Path:
    root = (os.environ.get("ATP_STAGING_ROOT") or "").strip() or _DEFAULT_STAGING_ROOT
    return Path(root).resolve()


def _cursor_cli_path() -> str:
    return (os.environ.get("CURSOR_CLI_PATH") or "").strip() or _DEFAULT_CURSOR_CLI


def _find_mounted_cursor_cli() -> str:
    """
    Resolve Cursor CLI from mounted Cursor Server runtime, if present.

    Expected path pattern:
      /app/.cursor-server/bin/linux-x64/<commit>/bin/remote-cli/cursor
    """
    try:
        base = Path("/app/.cursor-server/bin/linux-x64")
        if not base.is_dir():
            return ""
        for commit_dir in sorted(base.iterdir(), reverse=True):
            candidate = commit_dir / "bin" / "remote-cli" / "cursor"
            if candidate.is_file():
                return str(candidate)
    except Exception:
        pass
    return ""


def _resolve_cursor_cli_binary() -> str:
    """
    Return an executable path/name for Cursor CLI.

    Resolution order:
    1) CURSOR_CLI_PATH (if absolute/relative path and exists)
    2) `which <CURSOR_CLI_PATH>` when it is a bare command name
    3) mounted Cursor Server remote-cli launcher under /app/.cursor-server
    """
    cli = _cursor_cli_path()
    if "/" in cli:
        return cli if Path(cli).exists() else ""
    try:
        r = subprocess.run(["which", cli], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and (r.stdout or "").strip():
            return (r.stdout or "").strip()
    except Exception:
        pass
    mounted = _find_mounted_cursor_cli()
    if mounted:
        return mounted
    return ""


def _cursor_api_key() -> str:
    return (os.environ.get("CURSOR_API_KEY") or "").strip()


def _cursor_agent_binary() -> str:
    """
    Prefer cursor-agent (supports --api-key). Only return paths executable by the current uid.

    Order: CURSOR_AGENT_PATH, /home/appuser/.local/bin (before /root — gunicorn runs as appuser),
    ``which cursor-agent``, skipping non-executable files (e.g. /root/.local/... for non-root).
    """
    explicit = (os.environ.get("CURSOR_AGENT_PATH") or "").strip()
    if explicit:
        p = Path(explicit)
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
        return ""
    for p in (Path("/home/appuser/.local/bin/cursor-agent"), Path("/root/.local/bin/cursor-agent")):
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    try:
        r = subprocess.run(["which", "cursor-agent"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and (r.stdout or "").strip():
            w = (r.stdout or "").strip()
            if os.access(w, os.X_OK):
                return w
    except Exception:
        pass
    return ""


def _cursor_timeout() -> int:
    raw = (os.environ.get("CURSOR_CLI_TIMEOUT") or "").strip()
    try:
        return int(raw) if raw else _DEFAULT_TIMEOUT
    except ValueError:
        return _DEFAULT_TIMEOUT


def _test_timeout() -> int:
    raw = (os.environ.get("CURSOR_BRIDGE_TEST_TIMEOUT") or "").strip()
    try:
        return int(raw) if raw else _DEFAULT_TEST_TIMEOUT
    except ValueError:
        return _DEFAULT_TEST_TIMEOUT


def is_bridge_enabled() -> bool:
    """True when CURSOR_BRIDGE_ENABLED is set to a truthy value."""
    v = (os.environ.get("CURSOR_BRIDGE_ENABLED") or "").strip().lower()
    return v in ("1", "true", "yes")


def is_bridge_require_approval() -> bool:
    """When True, API and scheduler must see patch approval before executing the bridge."""
    v = (os.environ.get("CURSOR_BRIDGE_REQUIRE_APPROVAL") or "").strip().lower()
    if v in ("0", "false", "no"):
        return False
    return True


def scheduler_should_auto_run_cursor_bridge() -> bool:
    """
    Whether the agent scheduler may auto-invoke the bridge for ready-for-patch tasks.

    Production-safe default: when unset, False (no scheduler auto-run). Opt in with
    CURSOR_BRIDGE_AUTO_IN_ADVANCE=true.
    """
    raw = (os.environ.get("CURSOR_BRIDGE_AUTO_IN_ADVANCE") or "").strip().lower()
    if raw in ("0", "false", "no"):
        return False
    if raw in ("1", "true", "yes"):
        return True
    return False


def _task_id_match_variants(task_id: str) -> set[str]:
    t = (task_id or "").strip()
    if not t:
        return set()
    out = {t, t.replace("-", "")}
    return {x for x in out if x}


def task_has_patch_approval(task_id: str, *, max_lines: int = 100_000) -> bool:
    """
    True if agent activity log contains patch_approved for this task (Telegram patch or investigation approve).

    Scans the tail of logs/agent_activity.jsonl (bounded) for event_type patch_approved.
    """
    variants_n = {v.replace("-", "") for v in _task_id_match_variants(task_id)}
    if not variants_n:
        return False
    try:
        path = _workspace_root() / _AGENT_ACTIVITY_LOG_DIR / _AGENT_ACTIVITY_LOG_FILE
        if not path.exists():
            return False
        buf: deque[str] = deque(maxlen=max(1000, max_lines))
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                buf.append(line)
        for line in reversed(buf):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event_type") != "patch_approved":
                continue
            ev_n = (row.get("task_id") or "").strip().replace("-", "")
            if ev_n and ev_n in variants_n:
                return True
        return False
    except Exception as e:
        logger.debug("cursor_bridge: task_has_patch_approval scan failed: %s", e)
        return False


def may_execute_cursor_bridge(task_id: str, *, context: str) -> tuple[bool, str]:
    """
    Enforce CURSOR_BRIDGE_REQUIRE_APPROVAL for api and scheduler contexts.

    context: "api" | "scheduler" | "telegram"
    """
    if not is_bridge_enabled():
        return False, "CURSOR_BRIDGE_ENABLED not set"
    ctx = (context or "").strip().lower()
    if ctx not in ("api", "scheduler", "telegram"):
        return False, "invalid execution context"
    if not is_bridge_require_approval():
        return True, ""
    if ctx == "telegram":
        return True, ""
    if task_has_patch_approval(task_id):
        return True, ""
    return False, (
        "CURSOR_BRIDGE_REQUIRE_APPROVAL: no patch_approved event for this task "
        "(approve patch in Telegram or set CURSOR_BRIDGE_REQUIRE_APPROVAL=false in non-prod only)"
    )


def _path_is_writable_dir(path: Path) -> bool:
    try:
        if not path.is_dir():
            return False
        probe = path / ".write_probe_diag"
        probe.write_text("", encoding="utf-8")  # pg-audit-ignore: staging-dir writability probe (not repo artifact)
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def get_bridge_diagnostics() -> dict[str, Any]:
    """
    Return readiness diagnostics for the Cursor bridge (no side effects).

    Useful for troubleshooting: env, Cursor CLI availability, staging root writable, etc.
    """
    cli = _cursor_cli_path()
    staging_root = _staging_root()
    try:
        handoff_dir = _handoffs_dir_for_bridge()
    except Exception as e:
        handoff_dir = _workspace_root() / "docs" / "agents" / "cursor-handoffs"
        logger.debug("get_bridge_diagnostics: handoff dir fallback: %s", e)

    # Check if Cursor CLI is resolvable
    cursor_found = False
    try:
        cursor_found = bool(_resolve_cursor_cli_binary())
    except Exception:
        pass

    # Check staging root writable
    staging_writable = False
    try:
        staging_root.mkdir(parents=True, exist_ok=True)
        test_file = staging_root / ".bridge_diag_write_test"
        test_file.write_text("ok")  # pg-audit-ignore: staging-root writability probe
        test_file.unlink()
        staging_writable = True
    except Exception:
        pass

    return {
        "enabled": is_bridge_enabled(),
        "require_approval": is_bridge_require_approval(),
        "scheduler_auto_bridge": scheduler_should_auto_run_cursor_bridge(),
        "cursor_cli_path": cli,
        "cursor_cli_found": cursor_found,
        "staging_root": str(staging_root),
        "staging_root_writable": staging_writable,
        "staging_dir_count": _count_staging_dirs(),
        "max_staging_dirs": _MAX_STAGING_DIRS,
        "handoff_dir": str(handoff_dir),
        "handoff_dir_exists": handoff_dir.is_dir(),
        "handoff_dir_writable": _path_is_writable_dir(handoff_dir),
        "github_token_set": bool((os.environ.get("GITHUB_TOKEN") or "").strip()),
        "ready": is_bridge_enabled() and cursor_found and staging_writable,
    }


def _notify_cursor_bridge_failure(title: str, detail: str) -> None:
    """Best-effort Telegram ops alert for scheduler/API failures (never raises)."""
    try:
        from app.services.telegram_notifier import telegram_notifier
        if not getattr(telegram_notifier, "enabled", False):
            return
        msg = f"⚠️ {title}\n{detail}"[:3500]
        telegram_notifier.send_message(msg, chat_destination="ops")
    except Exception as e:
        logger.debug("cursor_bridge: failure notify skipped: %s", e)


def _log_event(event_type: str, task_id: str = "", details: dict | None = None) -> None:
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(event_type, task_id=task_id or None, details=details or {})
    except Exception as e:
        logger.debug("cursor_bridge: log_agent_event failed: %s", e)


def _count_staging_dirs() -> int:
    """Count existing staging directories."""
    root = _staging_root()
    if not root.is_dir():
        return 0
    return sum(1 for p in root.iterdir() if p.is_dir() and p.name.startswith("atp-"))


def provision_staging_workspace(task_id: str) -> Path | None:
    """
    Clone ATP into a dedicated staging directory for the task.

    Returns the path to the staging directory on success, None on failure.
    Never modifies the ATP source.
    """
    task_id = (task_id or "").strip()
    if not task_id:
        logger.warning("cursor_bridge: provision_staging_workspace empty task_id")
        return None

    root = _workspace_root()
    staging_root = _staging_root()
    staging_dir = staging_root / f"atp-{task_id}"

    if staging_dir.exists():
        logger.info("cursor_bridge: staging dir already exists task_id=%s path=%s", task_id, staging_dir)
        _log_event("cursor_bridge_staging_exists", task_id=task_id, details={"path": str(staging_dir)})
        return staging_dir

    if _count_staging_dirs() >= _MAX_STAGING_DIRS:
        logger.warning("cursor_bridge: max staging dirs reached (%d) task_id=%s", _MAX_STAGING_DIRS, task_id)
        _log_event("cursor_bridge_staging_limit", task_id=task_id, details={"max": _MAX_STAGING_DIRS})
        return None

    try:
        staging_root.mkdir(parents=True, exist_ok=True)

        # Git's ownership check for local-path clones can require global safe.directory
        # entries even when `-c safe.directory=...` is provided on clone.
        for safe_path in (str(root), str(root / ".git")):
            subprocess.run(
                ["git", "config", "--global", "--add", "safe.directory", safe_path],
                capture_output=True,
                text=True,
                timeout=10,
            )

        # Clone from local repo (workspace_root) to get current state
        result = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={root}",
                "-c",
                f"safe.directory={root / '.git'}",
                "clone",
                "--depth",
                "1",
                str(root),
                str(staging_dir),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=staging_root.parent,
        )
        if result.returncode != 0:
            logger.warning(
                "cursor_bridge: git clone failed task_id=%s code=%s stderr=%s",
                task_id, result.returncode, (result.stderr or "")[:500],
            )
            _log_event("cursor_bridge_staging_failed", task_id=task_id, details={
                "error": result.stderr[:500] if result.stderr else "git clone failed",
            })
            return None

        # Ensure origin points to GitHub (clone from local path sets origin to local path)
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(staging_dir),
            capture_output=True,
            text=True,
            timeout=5,
        )
        url = (remote.stdout or "").strip()
        if url and "github.com" not in url:
            repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip() or _DEFAULT_REPO
            gh_url = f"https://github.com/{repo}.git"
            subprocess.run(["git", "remote", "set-url", "origin", gh_url], cwd=str(staging_dir), capture_output=True, timeout=5)

        logger.info("cursor_bridge: staging provisioned task_id=%s path=%s", task_id, staging_dir)
        _log_event("cursor_bridge_staging_provisioned", task_id=task_id, details={"path": str(staging_dir)})
        return staging_dir

    except subprocess.TimeoutExpired:
        logger.warning("cursor_bridge: git clone timeout task_id=%s", task_id)
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        _log_event("cursor_bridge_staging_timeout", task_id=task_id, details={})
        return None
    except Exception as e:
        logger.exception("cursor_bridge: provision_staging_workspace failed task_id=%s", task_id)
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        _log_event("cursor_bridge_staging_error", task_id=task_id, details={"error": str(e)})
        return None


def invoke_cursor_cli(staging_path: Path, prompt: str, *, task_id: str = "") -> dict[str, Any]:
    """
    Run Cursor CLI in non-interactive mode with the given prompt.

    Cursor has full write access in non-interactive mode (-p). Runs in staging_path.

    Returns dict with: success (bool), exit_code (int), output (str), error (str|None).
    """
    api_key = _cursor_api_key()
    agent_cli = _cursor_agent_binary() if api_key else ""
    cli = agent_cli or _resolve_cursor_cli_binary()
    timeout = _cursor_timeout()

    if not cli:
        return {
            "success": False,
            "exit_code": -1,
            "output": "",
            "error": "Cursor CLI not found (checked CURSOR_CLI_PATH/which and /app/.cursor-server mount)",
        }
    if not api_key and "/app/.cursor-server/" in cli:
        return {
            "success": False,
            "exit_code": -1,
            "output": "",
            "error": (
                "Cursor non-interactive auth unavailable: CURSOR_API_KEY is not set and in-container cursor-agent is not logged in. "
                "Set CURSOR_API_KEY in runtime env for headless bridge runs."
            ),
        }
    if "cursor-agent" in Path(cli).name:
        args = [cli, "-p", "--output-format", "json"]
        if api_key:
            args.extend(["--api-key", api_key])
        args.append(prompt)
    else:
        args = [cli, "agent", "-p", "--output-format", "json"]
        if api_key:
            args.extend(["--api-key", api_key])
        args.append(prompt)

    logger.info("CursorBridge: applying patch task_id=%s staging=%s", task_id, staging_path)
    logger.info(
        "cursor_bridge: invoking CLI task_id=%s path=%s timeout=%ds prompt_len=%d",
        task_id, staging_path, timeout, len(prompt),
    )
    _log_event("cursor_bridge_invoke_start", task_id=task_id, details={
        "staging_path": str(staging_path),
        "prompt_len": len(prompt),
    })

    try:
        result = subprocess.run(
            args,
            cwd=str(staging_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout or "").strip()
        err_out = (result.stderr or "").strip()
        success = result.returncode == 0

        logger.info(
            "cursor_bridge: CLI finished task_id=%s success=%s exit_code=%d output_len=%d",
            task_id, success, result.returncode, len(output),
        )
        _log_event(
            "cursor_bridge_invoke_done" if success else "cursor_bridge_invoke_failed",
            task_id=task_id,
            details={
                "exit_code": result.returncode,
                "output_len": len(output),
                "success": success,
            },
        )

        return {
            "success": success,
            "exit_code": result.returncode,
            "output": output,
            "error": err_out if not success else None,
        }

    except subprocess.TimeoutExpired:
        logger.warning("cursor_bridge: CLI timeout task_id=%s after %ds", task_id, timeout)
        _log_event("cursor_bridge_invoke_timeout", task_id=task_id, details={"timeout": timeout})
        return {
            "success": False,
            "exit_code": -1,
            "output": "",
            "error": f"timeout after {timeout}s",
        }
    except Exception as e:
        logger.exception("cursor_bridge: invoke_cursor_cli failed task_id=%s", task_id)
        _log_event("cursor_bridge_invoke_error", task_id=task_id, details={"error": str(e)})
        return {
            "success": False,
            "exit_code": -1,
            "output": "",
            "error": str(e),
        }


def cleanup_staging(task_id: str) -> bool:
    """Remove the staging directory for the task. Returns True if removed or already gone."""
    task_id = (task_id or "").strip()
    if not task_id:
        return False
    staging_dir = _staging_root() / f"atp-{task_id}"
    if not staging_dir.exists():
        return True
    try:
        shutil.rmtree(staging_dir)
        logger.info("cursor_bridge: cleanup done task_id=%s path=%s", task_id, staging_dir)
        _log_event("cursor_bridge_cleanup", task_id=task_id, details={"path": str(staging_dir)})
        return True
    except Exception as e:
        logger.warning("cursor_bridge: cleanup failed task_id=%s: %s", task_id, e)
        return False


def capture_diff(staging_path: Path, task_id: str) -> Path | None:
    """
    Run git diff in staging and save to docs/agents/patches/{task_id}.diff in ATP workspace.

    Returns the path to the diff file on success, None on failure.
    """
    task_id = (task_id or "").strip()
    if not task_id:
        return None
    try:
        result = subprocess.run(
            ["git", "diff", "--no-color"],
            cwd=str(staging_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        diff_content = (result.stdout or "").strip()
        if not diff_content:
            logger.info("cursor_bridge: no diff captured task_id=%s (clean or no changes)", task_id)
            _log_event("cursor_bridge_diff_empty", task_id=task_id, details={})
            return None

        from app.services import path_guard

        out_dir = _workspace_root() / _PATCHES_SUBDIR
        path_guard.safe_mkdir_lab(out_dir, context="cursor_execution_bridge:patches_dir")
        diff_path = out_dir / f"{task_id}.diff"
        path_guard.safe_write_text(diff_path, diff_content, context="cursor_execution_bridge:diff")

        logger.info("cursor_bridge: diff captured task_id=%s path=%s len=%d", task_id, diff_path, len(diff_content))
        _log_event("cursor_bridge_diff_captured", task_id=task_id, details={
            "path": str(diff_path),
            "len": len(diff_content),
        })
        return diff_path
    except subprocess.TimeoutExpired:
        logger.warning("cursor_bridge: git diff timeout task_id=%s", task_id)
        return None
    except Exception as e:
        logger.warning("cursor_bridge: capture_diff failed task_id=%s: %s", task_id, e)
        return None


def run_tests_in_staging(staging_path: Path, *, task_id: str = "") -> dict[str, Any]:
    """
    Run backend pytest and frontend lint/build in staging.

    Returns dict with: backend_ok, frontend_ok, backend_output, frontend_output, all_ok.
    """
    timeout = _test_timeout()
    backend_ok = False
    frontend_ok = False
    backend_output = ""
    frontend_output = ""

    # Backend: pytest -q
    backend_dir = staging_path / "backend"
    if backend_dir.is_dir():
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "-q", "--tb=short"],
                cwd=str(backend_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            backend_output = (result.stdout or "") + (result.stderr or "")
            backend_ok = result.returncode == 0
            logger.info(
                "cursor_bridge: backend tests task_id=%s ok=%s exit=%d",
                task_id, backend_ok, result.returncode,
            )
        except subprocess.TimeoutExpired:
            backend_output = f"pytest timeout after {timeout}s"
            logger.warning("cursor_bridge: backend pytest timeout task_id=%s", task_id)
        except FileNotFoundError:
            backend_output = "pytest not found"
            logger.warning("cursor_bridge: pytest not found task_id=%s", task_id)
        except Exception as e:
            backend_output = str(e)
            logger.warning("cursor_bridge: backend tests failed task_id=%s: %s", task_id, e)
    else:
        backend_output = "backend dir not found"
        backend_ok = True  # Skip if no backend

    # Frontend: npm run lint && npm run build
    frontend_dir = staging_path / "frontend"
    if frontend_dir.is_dir() and (frontend_dir / "package.json").exists():
        try:
            result = subprocess.run(
                ["npm", "run", "lint", "--if-present"],
                cwd=str(frontend_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            lint_out = (result.stdout or "") + (result.stderr or "")
            lint_ok = result.returncode == 0
            if not lint_ok:
                frontend_output = lint_out
                frontend_ok = False
            else:
                result = subprocess.run(
                    ["npm", "run", "build"],
                    cwd=str(frontend_dir),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                frontend_output = (result.stdout or "") + (result.stderr or "")
                frontend_ok = result.returncode == 0
            logger.info(
                "cursor_bridge: frontend tests task_id=%s ok=%s",
                task_id, frontend_ok,
            )
        except subprocess.TimeoutExpired:
            frontend_output = f"npm timeout after {timeout}s"
            frontend_ok = False
            logger.warning("cursor_bridge: frontend timeout task_id=%s", task_id)
        except FileNotFoundError:
            frontend_output = "npm not found"
            frontend_ok = False
        except Exception as e:
            frontend_output = str(e)
            frontend_ok = False
    else:
        frontend_ok = True  # Skip if no frontend

    all_ok = backend_ok and frontend_ok
    if all_ok:
        logger.info("CursorBridge: tests passed task_id=%s", task_id)
    else:
        logger.warning("CursorBridge: tests failed task_id=%s", task_id)
    _log_event(
        "cursor_bridge_tests_done" if all_ok else "cursor_bridge_tests_failed",
        task_id=task_id,
        details={
            "backend_ok": backend_ok,
            "frontend_ok": frontend_ok,
            "all_ok": all_ok,
        },
    )

    return {
        "backend_ok": backend_ok,
        "frontend_ok": frontend_ok,
        "all_ok": all_ok,
        "backend_output": backend_output[:2000] if backend_output else "",
        "frontend_output": frontend_output[:2000] if frontend_output else "",
    }


def ingest_bridge_results(
    task_id: str,
    *,
    invoke_ok: bool,
    tests_ok: bool,
    diff_path: Path | str | None = None,
    tests: dict[str, Any] | None = None,
    current_status: str = "patching",
    advance_on_pass: bool = True,
) -> dict[str, Any]:
    """
    Feed bridge results into Notion and the test gate.

    Calls record_test_result with outcome (passed/failed/partial/not-run) and
    updates Notion metadata (cursor_patch_url for diff path). Advances task
    to ready-for-deploy when tests pass and advance_on_pass is True.
    """
    task_id = (task_id or "").strip()
    if not task_id:
        return {"ok": False, "error": "empty task_id"}

    # Map to test outcome
    if not invoke_ok:
        outcome = "not-run"
        summary = "Cursor invoke failed — tests not run"
    elif tests is None:
        outcome = "not-run"
        summary = "Tests not executed"
    elif tests_ok:
        outcome = "passed"
        parts = []
        if tests.get("backend_ok") is not False:
            parts.append("backend ok")
        if tests.get("frontend_ok") is not False:
            parts.append("frontend ok")
        summary = "; ".join(parts) or "all tests passed"
    elif tests.get("backend_ok") and tests.get("frontend_ok") is False:
        outcome = "partial"
        summary = "backend passed; frontend failed"
    elif tests.get("frontend_ok") and tests.get("backend_ok") is False:
        outcome = "partial"
        summary = "frontend passed; backend failed"
    else:
        outcome = "failed"
        summary = "backend and frontend tests failed"

    if diff_path:
        diff_rel = str(diff_path)
        if hasattr(diff_path, "relative_to"):
            try:
                diff_rel = str(Path(diff_path).relative_to(_workspace_root()))
            except ValueError:
                pass
        summary = f"{summary} | diff: {diff_rel}"

    try:
        from app.services.task_test_gate import record_test_result

        gate_result = record_test_result(
            task_id,
            outcome,
            summary=summary,
            advance_on_pass=advance_on_pass,
            current_status=current_status,
        )
    except Exception as e:
        logger.warning("cursor_bridge: ingest record_test_result failed task_id=%s: %s", task_id, e)
        gate_result = {"ok": False, "error": str(e)}

    # Update cursor_patch_url if we have a diff
    if diff_path and gate_result.get("ok"):
        try:
            from app.services.notion_tasks import update_notion_task_metadata

            diff_str = str(diff_path)
            if hasattr(diff_path, "relative_to"):
                try:
                    diff_str = str(Path(diff_path).relative_to(_workspace_root()))
                except ValueError:
                    pass
            update_notion_task_metadata(
                task_id,
                {"cursor_patch_url": diff_str},
                append_comment=f"[Cursor bridge] Patch diff saved: {diff_str}",
            )
        except Exception as e:
            logger.debug("cursor_bridge: cursor_patch_url update failed task_id=%s: %s", task_id, e)

    _log_event("cursor_bridge_ingest_done", task_id=task_id, details={
        "outcome": outcome,
        "advanced": gate_result.get("advanced", False),
        "advanced_to": gate_result.get("advanced_to", ""),
    })

    return {
        "ok": gate_result.get("ok", False),
        "outcome": outcome,
        "gate_result": gate_result,
    }


def _cursor_handoff_path(task_id: str) -> Path:
    tid = (task_id or "").strip()
    return _handoffs_dir_for_bridge() / f"cursor-handoff-{tid}.md"


def ensure_handoff_file_for_bridge(task_id: str) -> tuple[bool, str]:
    """
    Ensure ``cursor-handoff-{task_id}.md`` exists under docs/agents/cursor-handoffs.

    If missing, loads the task from Notion and runs ``generate_cursor_handoff`` (sections
    from sidecar when present). Does not bypass approval or bridge enabled checks (caller
    runs those first).

    Returns (ok, error_message).
    """
    tid = (task_id or "").strip()
    if not tid:
        return False, "empty task_id"

    path = _cursor_handoff_path(tid)
    out_dir = path.parent
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning(
            "CursorBridge: handoff dir mkdir failed path=%s err=%s",
            out_dir,
            e,
        )
    dir_exists = out_dir.is_dir()
    dir_writable = _path_is_writable_dir(out_dir)
    logger.info(
        "CursorBridge: handoff path=%s dir=%s exists=%s writable=%s",
        path,
        out_dir,
        dir_exists,
        dir_writable,
    )

    if path.exists():
        logger.info("CursorBridge: handoff ready path=%s", path)
        return True, ""

    logger.warning("CursorBridge: handoff missing; auto-generating task_id=%s", tid)
    logger.info("CursorBridge: writing handoff file %s", path)

    try:
        from app.services.notion_task_reader import get_notion_task_by_id
        from app.services.cursor_handoff import generate_cursor_handoff

        task = get_notion_task_by_id(tid)
        if not task:
            return False, (
                f"handoff file not found and Notion task unavailable for task_id={tid}; "
                "cannot auto-generate handoff"
            )

        task = dict(task)
        task["id"] = tid

        prepared_task: dict[str, Any] = {"task": task, "_openclaw_sections": {}}
        try:
            from app.services.agent_task_executor import infer_repo_area_for_task
            prepared_task["repo_area"] = infer_repo_area_for_task(task)
        except Exception:
            prepared_task["repo_area"] = {}

        result = generate_cursor_handoff(prepared_task)
        if not result.get("success"):
            err_detail = (
                result.get("path")
                or "save failed — check logs for save_cursor_handoff (Permission denied etc.)"
            )
            return False, (
                f"handoff auto-generation failed for task_id={tid} "
                f"(generate_cursor_handoff returned success=False; detail={err_detail})"
            )
        if not path.exists():
            return False, (
                f"handoff auto-generation reported success but file missing: {path}"
            )

        logger.info("CursorBridge: handoff auto-generated path=%s", path)
        logger.info("CursorBridge: handoff ready path=%s", path)
        _log_event("cursor_bridge_handoff_auto_generated", task_id=tid, details={"path": str(path)})
        return True, ""

    except Exception as e:
        logger.exception("CursorBridge: handoff auto-generation failed task_id=%s", tid)
        return False, f"handoff auto-generation error: {e}"


def run_bridge_phase1(
    task_id: str,
    prompt: str | None = None,
    *,
    execution_context: str = "api",
) -> dict[str, Any]:
    """
    Phase 1: Provision staging, invoke Cursor CLI, return result. No cleanup by default.

    If prompt is None, loads from docs/agents/cursor-handoffs/cursor-handoff-{task_id}.md.
    """
    task_id = (task_id or "").strip()
    if not task_id:
        return {"ok": False, "error": "empty task_id"}

    ctx = (execution_context or "api").strip().lower()
    if ctx not in ("api", "scheduler", "telegram"):
        ctx = "api"
    may_ok, may_err = may_execute_cursor_bridge(task_id, context=ctx)
    if not may_ok:
        return {"ok": False, "error": may_err, "task_id": task_id}

    if prompt is None:
        handoff_path = _cursor_handoff_path(task_id)
        ok_handoff, handoff_err = ensure_handoff_file_for_bridge(task_id)
        if not ok_handoff:
            err_msg = handoff_err or f"handoff file not found: {handoff_path}"
            logger.warning(
                "cursor_bridge: handoff missing/failed task_id=%s path=%s error=%s",
                task_id, handoff_path, err_msg[:200],
            )
            _log_event("cursor_bridge_handoff_missing", task_id=task_id, details={"error": err_msg[:300]})
            return {
                "ok": False,
                "error": err_msg,
                "task_id": task_id,
                "failure_point": "handoff_missing_or_auto_gen_failed",
            }
        prompt = handoff_path.read_text(encoding="utf-8")

    staging_path = provision_staging_workspace(task_id)
    if not staging_path:
        return {"ok": False, "error": "staging provision failed"}

    invoke_result = invoke_cursor_cli(staging_path, prompt, task_id=task_id)

    return {
        "ok": invoke_result["success"],
        "task_id": task_id,
        "staging_path": str(staging_path),
        "invoke": invoke_result,
        "cleanup": False,  # Caller may want to inspect; call cleanup_staging explicitly
    }


def create_patch_pr(
    staging_path: Path,
    task_id: str,
    *,
    title: str = "",
    base_ref: str = "main",
) -> dict[str, Any]:
    """
    Create a PR from staging changes. Requires GITHUB_TOKEN and uncommitted changes.

    Returns dict with: ok, pr_url, pr_number, error.
    """
    task_id = (task_id or "").strip()
    if not task_id:
        return {"ok": False, "pr_url": None, "pr_number": None, "error": "empty task_id"}

    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip() or _DEFAULT_REPO
    if not token:
        return {"ok": False, "pr_url": None, "pr_number": None, "error": "GITHUB_TOKEN not set"}

    # Sanitize branch name: alphanumeric and hyphens only
    safe_id = re.sub(r"[^a-zA-Z0-9-]", "-", task_id)[:50].strip("-") or "patch"
    branch_name = f"cursor-patch-{safe_id}"

    try:
        # Check for changes
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(staging_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if status.returncode != 0 or not (status.stdout or "").strip():
            return {"ok": False, "pr_url": None, "pr_number": None, "error": "no changes to commit"}

        # Create branch, add, commit
        subprocess.run(["git", "checkout", "-b", branch_name], cwd=str(staging_path), capture_output=True, timeout=10, check=True)
        subprocess.run(["git", "add", "-A"], cwd=str(staging_path), capture_output=True, timeout=10, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"[cursor-bridge] Patch for task {task_id[:20]}"],
            cwd=str(staging_path),
            capture_output=True,
            timeout=10,
            check=True,
        )

        # Set remote URL with token for push (clone uses origin without auth)
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(staging_path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        url = (remote.stdout or "").strip()
        if url.startswith("https://") and "github.com" in url and token:
            auth_url = url.replace("https://", f"https://x-access-token:{token}@")
            subprocess.run(["git", "remote", "set-url", "origin", auth_url], cwd=str(staging_path), capture_output=True, timeout=5)

        push = subprocess.run(
            ["git", "push", "-u", "origin", branch_name],
            cwd=str(staging_path),
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "GIT_ASKPASS": "", "GIT_TERMINAL_PROMPT": "0"},
        )
        if push.returncode != 0:
            err = (push.stderr or push.stdout or "push failed")[:500]
            return {"ok": False, "pr_url": None, "pr_number": None, "error": f"git push failed: {err}"}

        # Create PR via GitHub API
        pr_title = (title or "").strip() or f"[Cursor bridge] Patch for task {task_id[:30]}"
        pr_body = f"Automated patch from Cursor Execution Bridge.\n\nNotion task: `{task_id}`\n\nReview and merge to main when ready."
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        payload = {"title": pr_title[:256], "body": pr_body, "head": branch_name, "base": base_ref}

        with httpx.Client(timeout=15.0) as client:
            resp = client.post(f"{_GITHUB_API}/repos/{repo}/pulls", headers=headers, json=payload)

        if resp.status_code not in (200, 201):
            return {"ok": False, "pr_url": None, "pr_number": None, "error": f"GitHub API {resp.status_code}: {resp.text[:300]}"}

        data = resp.json()
        pr_url = data.get("html_url", "")
        pr_number = data.get("number")

        logger.info("cursor_bridge: PR created task_id=%s url=%s", task_id, pr_url)
        _log_event("cursor_bridge_pr_created", task_id=task_id, details={"pr_url": pr_url, "pr_number": pr_number})

        return {"ok": True, "pr_url": pr_url, "pr_number": pr_number, "error": None}

    except subprocess.CalledProcessError as e:
        return {"ok": False, "pr_url": None, "pr_number": None, "error": f"git command failed: {e}"}
    except Exception as e:
        logger.warning("cursor_bridge: create_patch_pr failed task_id=%s: %s", task_id, e)
        return {"ok": False, "pr_url": None, "pr_number": None, "error": str(e)}


def run_bridge_phase2(
    task_id: str,
    prompt: str | None = None,
    *,
    ingest: bool = True,
    create_pr: bool = False,
    current_status: str = "patching",
    execution_context: str = "api",
) -> dict[str, Any]:
    """
    Phase 2: Phase 1 + diff capture + test execution + result ingestion + optional PR.

    Runs: provision → invoke → capture_diff → run_tests_in_staging → ingest_bridge_results
    → create_patch_pr (if create_pr=True and tests pass).
    When ingest=True (default), feeds results to record_test_result and Notion.

    execution_context: api | scheduler | telegram — controls approval bypass (telegram) and alerts (scheduler).
    """
    task_id = (task_id or "").strip()
    ctx = (execution_context or "api").strip().lower()
    if ctx not in ("api", "scheduler", "telegram"):
        ctx = "api"

    with _cursor_bridge_phase2_lock(task_id) as lock_ok:
        if not lock_ok:
            return {
                "ok": False,
                "error": "cursor bridge already running for this task (duplicate request skipped)",
                "task_id": task_id,
                "duplicate_skipped": True,
            }
        logger.info("CursorBridge: patch detected task_id=%s context=%s", task_id, ctx)
        _log_event("cursor_bridge_started", task_id=task_id, details={
            "ingest": ingest, "create_pr": create_pr, "execution_context": ctx,
        })
        phase1 = run_bridge_phase1(task_id=task_id, prompt=prompt, execution_context=ctx)
        if not phase1.get("ok"):
            if ctx == "scheduler":
                _notify_cursor_bridge_failure(
                    "Cursor bridge: apply failed",
                    f"task_id={task_id[:24]}… error={str(phase1.get('error', ''))[:400]}",
                )
            return phase1

        staging_path_str = phase1.get("staging_path", "")
        staging_path = Path(staging_path_str) if staging_path_str else None
        if not staging_path or not staging_path.exists():
            return {**phase1, "diff_path": None, "tests": None, "ingest": None, "pr": None}

        diff_path = capture_diff(staging_path, task_id)
        tests = run_tests_in_staging(staging_path, task_id=task_id)

        invoke_ok = phase1.get("invoke", {}).get("success", False)
        tests_ok = tests.get("all_ok", False)

        if invoke_ok and not tests_ok:
            logger.warning(
                "CursorBridge: tests failed — rolling back workspace diff and staging task_id=%s",
                task_id,
            )
            if diff_path and diff_path.exists():
                try:
                    diff_path.unlink()
                except OSError as e:
                    logger.warning("cursor_bridge: rollback diff unlink failed task_id=%s: %s", task_id, e)
            cleanup_staging(task_id)
            diff_path = None
            _log_event("cursor_bridge_rollback_tests_failed", task_id=task_id, details={
                "backend_ok": tests.get("backend_ok"),
                "frontend_ok": tests.get("frontend_ok"),
            })
            _notify_cursor_bridge_failure(
                "Cursor bridge: tests failed (rolled back diff)",
                f"task_id={task_id[:24]}… backend_ok={tests.get('backend_ok')} frontend_ok={tests.get('frontend_ok')}",
            )

        overall_ok = invoke_ok and tests_ok

        result: dict[str, Any] = {
            **phase1,
            "ok": overall_ok,
            "diff_path": str(diff_path) if diff_path else None,
            "tests": tests,
            "invoke_ok": invoke_ok,
            "tests_ok": tests_ok,
        }

        if ingest:
            dp = Path(diff_path) if diff_path else None
            ingest_result = ingest_bridge_results(
                task_id,
                invoke_ok=invoke_ok,
                tests_ok=tests_ok,
                diff_path=dp,
                tests=tests,
                current_status=current_status,
            )
            result["ingest"] = ingest_result

        if create_pr and tests_ok and diff_path:
            pr_result = create_patch_pr(staging_path, task_id)
            result["pr"] = pr_result
            if pr_result.get("ok") and pr_result.get("pr_url"):
                try:
                    from app.services.notion_tasks import update_notion_task_metadata
                    update_notion_task_metadata(
                        task_id,
                        {"cursor_patch_url": pr_result["pr_url"]},
                        append_comment=f"[Cursor bridge] PR created: {pr_result['pr_url']}",
                    )
                except Exception as e:
                    logger.debug("cursor_bridge: Notion PR link update failed: %s", e)

        if overall_ok:
            logger.info("CursorBridge: deploy success (release candidate path) task_id=%s", task_id)
            _log_event("cursor_bridge_succeeded", task_id=task_id, details={
                "diff_path": str(diff_path) if diff_path else None,
                "tests_ok": tests_ok,
            })
        else:
            logger.warning(
                "CursorBridge: deploy failure (bridge did not complete) task_id=%s invoke_ok=%s tests_ok=%s",
                task_id, invoke_ok, tests_ok,
            )
            _log_event("cursor_bridge_failed", task_id=task_id, details={
                "invoke_ok": invoke_ok,
                "tests_ok": tests_ok,
            })
            if ctx == "scheduler" and not (invoke_ok and not tests_ok):
                _notify_cursor_bridge_failure(
                    "Cursor bridge: incomplete",
                    f"task_id={task_id[:24]}… invoke_ok={invoke_ok} tests_ok={tests_ok}",
                )

        return result
