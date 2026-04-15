"""
Secure Telegram intake for missing marketing settings (deterministic, no Bedrock).

Never logs or returns raw secret values. Uses ``secure_runtime_env_write`` + catalog metadata.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any
from urllib.parse import urlparse

from app.jarvis.dialog_state import DialogState, clear_secret_intake_only, get_state, set_state
from app.jarvis.marketing_intake_persist import try_hydrate_secret_intake_from_db, upsert_marketing_intake_state
from app.jarvis.marketing_settings_catalog import get_setting_meta, is_secret_setting
from app.jarvis.secure_runtime_env_write import persist_env_var_value

logger = logging.getLogger(__name__)

_CANCEL = frozenset({"cancel", "stop"})
_CHOICE_DASHBOARD = frozenset({"dashboard", "dash", "web"})
_CHOICE_TELEGRAM = frozenset({"telegram", "tg", "here"})


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _validate_value(setting_key: str, value: str) -> None:
    meta = get_setting_meta(setting_key)
    kind = str(meta.get("validation") or "non_empty") if meta else "non_empty"
    v = (value or "").strip()
    if not v:
        raise ValueError("empty")
    if "\n" in value or "\r" in value:
        raise ValueError("multiline")
    if kind == "numeric":
        if re.fullmatch(r"[0-9]+", v) or re.fullmatch(r"properties/[0-9]+", v, flags=re.IGNORECASE):
            return
        raise ValueError("numeric")
    if kind == "url":
        p = urlparse(v)
        if p.scheme not in ("http", "https") or not p.netloc:
            raise ValueError("url")
        return
    # non_empty
    return


def begin_marketing_setting_intake(
    chat_id: str,
    user_id: str,
    *,
    setting_key: str,
    resume_action: str = "run_marketing_review",
    resume_args: dict[str, Any] | None = None,
    runtime_env_path_override: str | None = None,
) -> str:
    """
    Start intake for one missing marketing setting. Returns the operator message to send (no secrets).
    """
    meta = get_setting_meta(setting_key)
    if meta is None:
        raise KeyError(f"unknown_setting:{setting_key}")

    st = get_state(chat_id, user_id) or DialogState()
    st.pending_secret_key = None
    st.pending_secret_label = None
    st.pending_secret_type = None
    st.pending_secret_env_var = None
    st.pending_secret_phase = ""

    st.pending_secret_key = setting_key
    st.pending_secret_label = str(meta.get("label") or setting_key)
    st.pending_secret_env_var = str(meta.get("env_var") or "")
    st.pending_secret_type = "secret" if is_secret_setting(setting_key) else "non_secret"
    st.pending_pipeline_to_resume = resume_action
    st.pending_pipeline_args = dict(resume_args or {})
    now = time.time()
    st.created_at = now
    st.secret_intake_started_at = now
    st.secret_intake_last_activity_at = now
    st.secret_runtime_env_path = runtime_env_path_override

    if st.pending_secret_type == "secret":
        st.pending_secret_phase = "choose"
        set_state(chat_id, user_id, st)
        upsert_marketing_intake_state(chat_id, user_id, st)
        return (
            f"I'm missing {st.pending_secret_label}.\n"
            "Reply `dashboard` to add it there, or `telegram` to provide it here securely."
        )

    st.pending_secret_phase = "await_value"
    set_state(chat_id, user_id, st)
    upsert_marketing_intake_state(chat_id, user_id, st)
    return (
        f"I'm missing {st.pending_secret_label}.\n"
        "Reply with the value in your next message (I won't repeat it back)."
    )


def _persist_and_resume(
    st: DialogState,
    chat_id: str,
    user_id: str,
    raw_value: str,
) -> dict[str, Any]:
    key = (st.pending_secret_key or "").strip()
    ev = (st.pending_secret_env_var or "").strip()
    if not key or not ev:
        raise ValueError("missing_meta")

    raw_stripped = raw_value.strip()
    _validate_value(key, raw_value)

    logger.info(
        "jarvis.secret_intake.persist_attempt setting_key=%s env_var=%s value_len=%d",
        key,
        ev,
        len(raw_stripped),
    )
    try:
        persist_env_var_value(ev, raw_stripped, path=st.secret_runtime_env_path)
    except ValueError:
        raise
    except Exception as e:
        logger.warning("jarvis.secret_intake.persist_failed key=%s err=%s", key, type(e).__name__)
        raise ValueError("persist_failed") from e

    proc_ok = bool((os.getenv(ev) or "").strip())
    logger.info(
        "jarvis.secret_intake.persist_ok setting_key=%s env_var=%s getenv_nonempty=%s",
        key,
        ev,
        proc_ok,
    )

    resume_action = (st.pending_pipeline_to_resume or "").strip() or "run_marketing_review"
    resume_args = dict(st.pending_pipeline_args or {})

    clear_secret_intake_only(chat_id, user_id)

    out: dict[str, Any] = {
        "dialog_message": "Received and saved securely. Continuing.",
        "resume_plan": {"action": resume_action, "args": resume_args},
    }
    return out


def handle_secret_intake_turn(
    raw: str,
    *,
    chat_id: str,
    user_id: str,
    runtime_env_path_override: str | None = None,
) -> dict[str, Any] | None:
    """
    Process one Telegram line when secret/plain marketing intake may be active.

    Returns a payload dict for the bot (``dialog_message``, optional ``resume_plan``) or ``None``.
    Never includes the submitted secret in any string field.
    """
    try:
        try_hydrate_secret_intake_from_db(chat_id, user_id)
    except Exception:
        logger.debug("jarvis.secret_intake.hydrate_skipped", exc_info=True)

    st = get_state(chat_id, user_id)
    if st is None or not (st.pending_secret_key and st.pending_secret_phase):
        return None

    st.secret_intake_last_activity_at = time.time()
    set_state(chat_id, user_id, st)
    upsert_marketing_intake_state(chat_id, user_id, st)

    text = (raw or "").strip()
    low = _norm(text)

    if low in _CANCEL:
        clear_secret_intake_only(chat_id, user_id)
        return {"dialog_message": "Cancelled secret intake."}

    phase = st.pending_secret_phase

    if phase == "choose":
        if low in _CHOICE_DASHBOARD:
            clear_secret_intake_only(chat_id, user_id)
            return {
                "dialog_message": (
                    "Use the trading dashboard → Missing marketing settings (admin key if required). "
                    "Values are not read from this chat anymore."
                )
            }
        if low in _CHOICE_TELEGRAM:
            st.pending_secret_phase = "await_value"
            set_state(chat_id, user_id, st)
            upsert_marketing_intake_state(chat_id, user_id, st)
            return {"dialog_message": "Send the value in your next message. I will not repeat it back."}
        return {
            "dialog_message": "Reply `dashboard` or `telegram` (or say cancel)."
        }

    if phase == "await_value":
        try:
            return _persist_and_resume(st, chat_id, user_id, text)
        except ValueError:
            return {
                "dialog_message": "That value looks invalid. Please try again or use the dashboard."
            }

    return None
