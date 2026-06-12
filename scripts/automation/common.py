"""Shared helpers for Jarvis production automations."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_DIR = Path("/var/lib/atp/jarvis_automations")
DEFAULT_BACKEND_BASE = "http://127.0.0.1:8002"
DEFAULT_DASHBOARD_URL = "https://dashboard.hilovivo.com"
DEFAULT_COOLDOWN_MINUTES = 30

ENV_FILES = (".env", ".env.local", ".env.aws", "secrets/runtime.env")


def repo_root() -> Path:
    return REPO_ROOT


def load_runtime_env() -> None:
    """Load env files without overwriting variables already set in the environment."""
    for name in ENV_FILES:
        path = REPO_ROOT / name
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


def automations_enabled() -> bool:
    return os.getenv("JARVIS_AUTOMATIONS_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def openclaw_public_allowed() -> bool:
    return os.getenv("OPENCLAW_PUBLIC_ALLOWED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def setup_logging(name: str, *, verbose: bool = False) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)sZ %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logger = logging.getLogger(name)
    for handler in logger.handlers:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)sZ %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
    return logger


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def backend_base() -> str:
    return (
        os.getenv("JARVIS_AUTOMATION_BACKEND_BASE")
        or os.getenv("ATP_HEALTH_BASE")
        or DEFAULT_BACKEND_BASE
    ).rstrip("/")


def dashboard_url() -> str:
    return (
        os.getenv("DASHBOARD_URL")
        or os.getenv("FRONTEND_URL")
        or DEFAULT_DASHBOARD_URL
    ).rstrip("/")


def state_dir() -> Path:
    raw = os.getenv("JARVIS_AUTOMATION_STATE_DIR", str(DEFAULT_STATE_DIR))
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def http_get(url: str, *, timeout: float = 10.0) -> tuple[bool, str, int | None]:
    """Return (ok, detail, status_code)."""
    ok, detail, code, _body = http_fetch(url, timeout=timeout)
    return ok, detail, code


def http_fetch(url: str, *, timeout: float = 10.0) -> tuple[bool, str, int | None, str]:
    """Return (ok, detail, status_code, body)."""
    try:
        req = Request(url, headers={"User-Agent": "atp-jarvis-automation/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            body = resp.read(8192).decode("utf-8", errors="replace")
            if 200 <= code < 300:
                return True, f"HTTP {code}", code, body
            return False, f"HTTP {code}: {body[:200]}", code, body
    except HTTPError as exc:
        body = exc.read(256).decode("utf-8", errors="replace") if exc.fp else ""
        return False, f"HTTP {exc.code}: {body[:200]}", exc.code, body
    except URLError as exc:
        return False, str(exc.reason)[:200], None, ""
    except Exception as exc:  # pragma: no cover - defensive
        return False, str(exc)[:200], None, ""


def docker_container_running(name_pattern: str) -> tuple[bool, str]:
    """Check docker ps for a running container matching name_pattern."""
    try:
        proc = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except FileNotFoundError:
        return False, "docker not installed"
    except subprocess.TimeoutExpired:
        return False, "docker ps timed out"

    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "docker ps failed")[:200]

    pattern = re.compile(re.escape(name_pattern), re.IGNORECASE)
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        name = parts[0]
        status = parts[1] if len(parts) > 1 else ""
        if pattern.search(name):
            if "up" in status.lower():
                return True, f"{name}: {status}"
            return False, f"{name}: {status}"
    return False, f"no running container matching {name_pattern!r}"


EXCHANGE_CREDENTIAL_WARN_RE = re.compile(
    r"API credentials not configured"
    r"|Crypto\.com API credentials not configured"
    r"|Missing EXCHANGE_CUSTOM_API_KEY"
    r"|Missing EXCHANGE_CUSTOM_API_SECRET"
    r"|Authentication failure"
    r"|40101"
    r"|not allowlisted"
    r"|authentication failed"
    r"|Crypto\.com API authentication",
    re.IGNORECASE,
)

EXCHANGE_LOG_FALSE_POSITIVE_RE = re.compile(
    r"password authentication failed",
    re.IGNORECASE,
)

HEALTH_LOG_FALSE_POSITIVE_RE = re.compile(
    r"last_error=None|last_error=\s*none",
    re.IGNORECASE,
)

HEALTH_LOG_ERROR_RE = re.compile(
    r"error|exception|critical",
    re.IGNORECASE,
)


def is_exchange_credential_warning(line: str) -> bool:
    """True when a log line reflects optional exchange integration, not a core outage."""
    if EXCHANGE_LOG_FALSE_POSITIVE_RE.search(line):
        return False
    return bool(EXCHANGE_CREDENTIAL_WARN_RE.search(line))


def exchange_credentials_configured() -> bool:
    key = os.getenv("EXCHANGE_CUSTOM_API_KEY", "").strip()
    secret = os.getenv("EXCHANGE_CUSTOM_API_SECRET", "").strip()
    return bool(key and secret)


def exchange_integration_optional() -> bool:
    """Missing exchange credentials are non-fatal when trading is off or trading-only."""
    trading_only = os.getenv("ATP_TRADING_ONLY", "").strip().lower()
    if trading_only in ("1", "true", "yes", "on"):
        return True

    ok, _, _, body = http_fetch(f"{backend_base()}/api/trading/live-status", timeout=5.0)
    if not ok or not body:
        return True

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return True

    if data.get("live_trading_enabled") is False:
        return True

    mode = str(data.get("mode", "")).upper()
    if mode in ("DRY_RUN", "PAPER", "DISABLED", "OFF", "UNKNOWN"):
        return True

    return False


def classify_exchange_credential_issue(
    *,
    log_warnings: list[str] | None = None,
) -> tuple[str, str]:
    """
    Classify Crypto.com credential/integration state for monitoring reports.

    Returns (severity, message) where severity is one of: ok, info, warning, error.
    Missing credentials never imply a production outage for core services.
    """
    warnings = log_warnings if log_warnings is not None else scan_exchange_credential_warnings(
        "backend-aws", tail=200
    )
    configured = exchange_credentials_configured()
    optional = exchange_integration_optional()

    if configured and not warnings:
        return "ok", "Crypto.com credentials configured"

    if not configured:
        msg = (
            "Crypto.com API credentials not configured "
            "(EXCHANGE_CUSTOM_API_KEY/EXCHANGE_CUSTOM_API_SECRET)"
        )
        return "warning", msg

    if warnings:
        snippet = warnings[0][:160]
        if optional:
            return "warning", snippet
        return "error", snippet

    return "info", "Crypto.com integration not required in current mode"


def fetch_docker_log_lines(service: str, *, tail: int = 100) -> list[str]:
    """Return recent docker compose log lines for a service."""
    try:
        proc = subprocess.run(
            ["docker", "compose", "--profile", "aws", "logs", "--tail", str(tail), service],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(REPO_ROOT),
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    if proc.returncode != 0 and not proc.stdout:
        return []

    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def scan_docker_logs(service: str, *, tail: int = 100, pattern: str = r"error|exception|critical") -> list[str]:
    """Return recent log lines matching error pattern for a compose service."""
    regex = re.compile(pattern, re.IGNORECASE)
    hits: list[str] = []
    for line in fetch_docker_log_lines(service, tail=tail):
        if regex.search(line):
            hits.append(line[:300])
    return hits[-5:]


def scan_exchange_credential_warnings(service: str = "backend-aws", *, tail: int = 120) -> list[str]:
    """Return recent exchange credential/auth warnings from backend logs."""
    hits: list[str] = []
    for line in fetch_docker_log_lines(service, tail=tail):
        if is_exchange_credential_warning(line):
            hits.append(line[:300])
    return hits[-5:]


def scan_docker_health_errors(service: str = "backend-aws", *, tail: int = 120) -> list[str]:
    """Return backend error log lines that indicate a real production outage."""
    hits: list[str] = []
    for line in fetch_docker_log_lines(service, tail=tail):
        if is_exchange_credential_warning(line):
            continue
        if HEALTH_LOG_FALSE_POSITIVE_RE.search(line):
            continue
        if HEALTH_LOG_ERROR_RE.search(line):
            hits.append(line[:300])
    return hits[-5:]


def check_websocket_prices(ws_url: str, *, timeout: float = 8.0) -> tuple[bool, str]:
    """Connect briefly to the prices WebSocket and expect a JSON message."""
    backend_path = REPO_ROOT / "backend"
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))

    try:
        import asyncio
        import websockets
    except ImportError:
        return False, "websockets package not available"

    async def _probe() -> tuple[bool, str]:
        try:
            async with websockets.connect(ws_url, open_timeout=timeout, close_timeout=2) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                if msg:
                    return True, "received price payload"
                return False, "empty websocket message"
        except Exception as exc:
            return False, str(exc)[:200]

    return asyncio.run(_probe())


def ws_prices_url() -> str:
    base = backend_base()
    if base.startswith("https://"):
        return base.replace("https://", "wss://", 1) + "/api/ws/prices"
    return base.replace("http://", "ws://", 1) + "/api/ws/prices"


class CooldownStore:
    """File-backed alert cooldown to reduce Telegram spam."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (state_dir() / "alert_cooldowns.json")
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self.path.is_file():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def should_send(self, alert_key: str, cooldown_minutes: int) -> bool:
        entry = self._data.get(alert_key)
        if not entry:
            return True
        last_sent = entry.get("last_sent_ts")
        if not last_sent:
            return True
        try:
            last_dt = datetime.fromisoformat(str(last_sent).replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60.0
            return age_min >= cooldown_minutes
        except (TypeError, ValueError):
            return True

    def mark_sent(self, alert_key: str) -> None:
        self._data[alert_key] = {"last_sent_ts": utc_now_iso()}
        self._save()

    def reset(self, alert_key: str | None = None) -> None:
        if alert_key is None:
            self._data = {}
        else:
            self._data.pop(alert_key, None)
        self._save()


def default_cooldown_minutes() -> int:
    raw = os.getenv("JARVIS_ALERT_COOLDOWN_MINUTES", str(DEFAULT_COOLDOWN_MINUTES))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_COOLDOWN_MINUTES


def ensure_backend_on_path() -> None:
    backend_path = str(REPO_ROOT / "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
