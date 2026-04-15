"""
In-memory Jarvis dialog / secret-intake state (Telegram chat + user scoped).

Bounded entries + TTL. Never store raw secret values after processing.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

_MAX_ENTRIES = 500
_TTL_SECONDS = 86400


def _secret_intake_ttl_seconds() -> float:
    """
    How long a marketing secret/plain intake session may sit idle before expiring.

    Default 24h so operators can step away; override with JARVIS_TELEGRAM_INTAKE_TTL_SECONDS (300–604800).
    """
    raw = (os.getenv("JARVIS_TELEGRAM_INTAKE_TTL_SECONDS") or "").strip()
    try:
        v = int(raw) if raw else 86400
    except ValueError:
        v = 86400
    return float(max(300, min(v, 604800)))


@dataclass
class DialogState:
    """Per (chat_id, user_id) conversational and secret-intake state."""

    created_at: float = field(default_factory=time.time)

    # Optional multi-step pipeline (ATP, etc.) — may be unused on thin branches
    pending_pipeline: str | None = None
    required_inputs: list[str] = field(default_factory=list)
    current_step: int = 0
    collected_inputs: dict[str, str] = field(default_factory=dict)
    missing_requirements: list[str] = field(default_factory=list)

    # Secure secret intake (never store raw secret after value phase completes)
    pending_secret_key: str | None = None
    pending_secret_label: str | None = None
    pending_secret_type: str | None = None  # "secret" | "non_secret"
    pending_secret_env_var: str | None = None
    pending_secret_phase: str = ""  # "" | "choose" | "await_value"
    pending_pipeline_to_resume: str | None = None
    pending_pipeline_args: dict[str, Any] = field(default_factory=dict)
    secret_intake_started_at: float | None = None
    secret_intake_last_activity_at: float | None = None
    secret_runtime_env_path: str | None = None


_store: dict[str, DialogState] = {}


def dialog_key(chat_id: str, user_id: str) -> str:
    return f"{(chat_id or '').strip()}:{(user_id or '').strip()}"


def _secret_flow_active(st: DialogState) -> bool:
    return bool((st.pending_secret_key or "").strip() and (st.pending_secret_phase or "").strip())


def _secret_intake_deadline(st: DialogState) -> float | None:
    base = st.secret_intake_last_activity_at or st.secret_intake_started_at
    if base is None:
        return None
    return float(base) + _secret_intake_ttl_seconds()


def get_state(chat_id: str, user_id: str) -> DialogState | None:
    _prune()
    st = _store.get(dialog_key(chat_id, user_id))
    if st is None:
        return None
    deadline = _secret_intake_deadline(st)
    if _secret_flow_active(st) and deadline is not None and time.time() > deadline:
        _clear_secret_portion(st)
        try:
            from app.jarvis.marketing_intake_persist import delete_marketing_intake_state

            delete_marketing_intake_state(chat_id, user_id)
        except Exception:
            pass
        if not _any_dialog_left(st):
            _store.pop(dialog_key(chat_id, user_id), None)
            return None
    return st


def set_state(chat_id: str, user_id: str, state: DialogState) -> None:
    _prune()
    key = dialog_key(chat_id, user_id)
    if len(_store) >= _MAX_ENTRIES and key not in _store:
        _evict_oldest()
    _store[key] = state


def clear_state(chat_id: str, user_id: str) -> None:
    _store.pop(dialog_key(chat_id, user_id), None)


def _clear_secret_portion(st: DialogState) -> None:
    st.pending_secret_key = None
    st.pending_secret_label = None
    st.pending_secret_type = None
    st.pending_secret_env_var = None
    st.pending_secret_phase = ""
    st.pending_pipeline_to_resume = None
    st.pending_pipeline_args = {}
    st.secret_intake_started_at = None
    st.secret_intake_last_activity_at = None
    st.secret_runtime_env_path = None


def clear_secret_intake_only(chat_id: str, user_id: str) -> None:
    st = _store.get(dialog_key(chat_id, user_id))
    if st is not None:
        _clear_secret_portion(st)
        if not _any_dialog_left(st):
            _store.pop(dialog_key(chat_id, user_id), None)
    try:
        from app.jarvis.marketing_intake_persist import delete_marketing_intake_state

        delete_marketing_intake_state(chat_id, user_id)
    except Exception:
        pass


def _any_dialog_left(st: DialogState) -> bool:
    if (st.pending_pipeline or "").strip():
        return True
    if st.required_inputs:
        return True
    return False


def _evict_oldest() -> None:
    if not _store:
        return
    oldest_k = min(_store.items(), key=lambda kv: kv[1].created_at)[0]
    _store.pop(oldest_k, None)


def _prune() -> None:
    now = time.time()
    dead = [k for k, v in _store.items() if now - v.created_at > _TTL_SECONDS]
    for k in dead:
        _store.pop(k, None)


def reset_store_for_tests() -> None:
    _store.clear()
