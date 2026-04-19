"""Jarvis: Bedrock-backed agent module (planner, tools, orchestrator)."""

def run_jarvis(*args, **kwargs):
    """Lazy import to avoid import-time dependency cycles during test collection."""
    from app.jarvis.orchestrator import run_jarvis as _run_jarvis

    return _run_jarvis(*args, **kwargs)

__all__ = ["run_jarvis"]
