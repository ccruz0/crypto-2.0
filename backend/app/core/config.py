import logging
import os
from typing import Optional, Tuple

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

_DEFAULT_ENV_FILES = (".env", "backend/.env", "secrets/runtime.env")


def readable_env_files(
    candidates: Tuple[str, ...] = _DEFAULT_ENV_FILES,
) -> Tuple[str, ...]:
    """Return env files the process can open.

    ``secrets/runtime.env`` is often host-owned ``600`` after render (umask 077).
    Container workers run as ``appuser`` and cannot read it; pydantic-settings then
    raises ``PermissionError`` on every ``Settings()`` (breaks Telegram refresh and
    signal_monitor). Entrypoint/compose already inject values into ``os.environ``,
    so skipping unreadable files is safe.
    """
    readable: list[str] = []
    for path in candidates:
        try:
            if os.path.isfile(path) and os.access(path, os.R_OK):
                readable.append(path)
        except OSError:
            continue
    return tuple(readable)


# Resolve TELEGRAM_BOT_TOKEN from env or by decrypting TELEGRAM_BOT_TOKEN_ENCRYPTED
# (secrets/runtime.env). Must run before Settings() so token is in os.environ.
def _inject_telegram_token_from_encrypted() -> None:
    from app.core.telegram_secrets import resolve_telegram_token_from_env
    token = resolve_telegram_token_from_env()
    if token:
        os.environ["TELEGRAM_BOT_TOKEN"] = token
        os.environ["TELEGRAM_BOT_TOKEN_AWS"] = token


class Settings(BaseSettings):
    PROJECT_NAME: str = "Automated Trading Platform"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = "postgresql://trader:traderpass@db:5432/atp"
    
    # Security
    # SECRET_KEY: Must be set via environment variable for security
    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    SECRET_KEY: Optional[str] = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Environment
    ENVIRONMENT: str = "local"
    # APP_ENV: Explicit environment identifier for alert routing ("aws" or "local")
    # Used to route alerts to different Telegram channels and prefix messages
    # Set APP_ENV=aws on AWS deployment, APP_ENV=local for local development
    APP_ENV: Optional[str] = None
    # RUN_TELEGRAM: Control whether Telegram messages are sent
    # Set RUN_TELEGRAM=true on AWS (where all Telegram messages must be sent)
    # Set RUN_TELEGRAM=false for local development (must never send Telegram messages)
    RUN_TELEGRAM: Optional[str] = None
    # RUNTIME_ORIGIN: Explicit runtime origin identifier ("AWS" or "LOCAL")
    # Used to enforce guards on order placement and Telegram alerts
    # Set RUNTIME_ORIGIN=AWS on AWS deployment (production)
    # Defaults to "LOCAL" for safety (prevents accidental production actions)
    RUNTIME_ORIGIN: str = "LOCAL"
    
    # Trading APIs
    BINANCE_API_KEY: Optional[str] = None
    BINANCE_SECRET_KEY: Optional[str] = None
    ALPACA_API_KEY: Optional[str] = None
    ALPACA_SECRET_KEY: Optional[str] = None
    NOTION_API_KEY: Optional[str] = None
    NOTION_TASK_DB: Optional[str] = None
    # Ops typo alias; code prefers NOTION_TASK_DB when both set
    NOTION_TASKS_DB: Optional[str] = None

    # OpenClaw integration (AI agent via HTTP API)
    OPENCLAW_API_URL: Optional[str] = None
    OPENCLAW_API_TOKEN: Optional[str] = None
    OPENCLAW_TIMEOUT_SECONDS: Optional[int] = None
    # Governance API (optional; falls back to OPENCLAW_API_TOKEN for Bearer auth)
    GOVERNANCE_API_TOKEN: Optional[str] = None
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    
    # Proxy settings
    USE_CRYPTO_PROXY: Optional[str] = None
    CRYPTO_PROXY_URL: Optional[str] = None
    CRYPTO_PROXY_TOKEN: Optional[str] = None
    LIVE_TRADING: Optional[str] = None

    # Telegram
    TELEGRAM_BOT_TOKEN: Optional[str] = None  # Deprecated: use TELEGRAM_BOT_TOKEN_AWS or TELEGRAM_BOT_TOKEN_LOCAL
    TELEGRAM_BOT_TOKEN_AWS: Optional[str] = None  # AWS production bot token
    TELEGRAM_BOT_TOKEN_LOCAL: Optional[str] = None  # Local development bot token (not used for sending)
    TELEGRAM_CHAT_ID: Optional[str] = None  # Deprecated: use TELEGRAM_CHAT_ID_AWS or TELEGRAM_CHAT_ID_LOCAL
    TELEGRAM_CHAT_ID_AWS: Optional[str] = None  # AWS production channel (trading)
    TELEGRAM_CHAT_ID_LOCAL: Optional[str] = None  # Local development channel (not used for sending)
    TELEGRAM_CHAT_ID_TRADING: Optional[str] = None  # ATP Alerts: signals, orders, reports
    TELEGRAM_CHAT_ID_OPS: Optional[str] = None  # AWS_alerts: health, anomalies, scheduler
    # ATP Control (@ATP_control_bot): tasks, investigations, approvals, needs revision, agent logs
    TELEGRAM_ATP_CONTROL_BOT_TOKEN: Optional[str] = None
    TELEGRAM_ATP_CONTROL_CHAT_ID: Optional[str] = None
    # Claw (@Claw_cruz_bot): control plane, user commands, /task /help, OpenClaw (responses)
    TELEGRAM_CLAW_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CLAW_CHAT_ID: Optional[str] = None

    class Config:
        # Do not bake env_file paths here — permissions change after render.
        # Callers use load_settings() / Settings(_env_file=readable_env_files()).
        env_file = None
        extra = "ignore"  # Ignore extra environment variables


def load_settings() -> Settings:
    """Build Settings from process env plus currently-readable env files only."""
    env_files = readable_env_files()
    return Settings(_env_file=env_files or None)


_inject_telegram_token_from_encrypted()
_env_files = readable_env_files()
if len(_env_files) < len(_DEFAULT_ENV_FILES):
    skipped = [p for p in _DEFAULT_ENV_FILES if p not in _env_files]
    logger.warning(
        "Settings skipping unreadable env file(s) %s (using process env / readable files only)",
        skipped,
    )
settings = load_settings()

# Validate SECRET_KEY is set (critical for security)
# For local/test: auto-generate if missing so scripts run without warnings
if not settings.SECRET_KEY or settings.SECRET_KEY in ("your-secret-key-here", "change-me"):
    import os
    if os.getenv("ENVIRONMENT") == "test" or os.getenv("APP_ENV") == "test":
        settings.SECRET_KEY = "test-secret-key-do-not-use-in-production"
    elif os.getenv("ENVIRONMENT") == "local" or os.getenv("APP_ENV") == "local" or not os.getenv("APP_ENV"):
        # Local dev: auto-generate ephemeral key so scheduler/scripts run without warnings
        import secrets
        settings.SECRET_KEY = secrets.token_urlsafe(32)
    else:
        import warnings
        warnings.warn(
            "SECRET_KEY is not set or using default value. "
            "This is a security risk. Set SECRET_KEY in your environment variables. "
            "Generate with: python -c 'import secrets; print(secrets.token_urlsafe(32))'",
            UserWarning
        )
