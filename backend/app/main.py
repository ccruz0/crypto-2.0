"""ASGI entrypoint for gunicorn/uvicorn (`app.main:app`). Application construction is in `app.factory.create_app`."""

from app.factory import (
    Base,
    DEBUG_DISABLE_SIGNAL_MONITOR,
    create_app,
    ensure_optional_columns,
    engine,
    trading_scheduler,
)

app = create_app(role="legacy")

__all__ = [
    "app",
    "Base",
    "DEBUG_DISABLE_SIGNAL_MONITOR",
    "create_app",
    "ensure_optional_columns",
    "engine",
    "trading_scheduler",
]
