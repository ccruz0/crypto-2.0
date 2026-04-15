"""
Persist Jarvis marketing secret/plain intake across process restarts (gunicorn max-requests, deploys).

In-memory DialogState remains authoritative while the process is warm; this store re-hydrates
before :func:`handle_secret_intake_turn` runs when memory was cleared or another worker recycled.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_TABLE = "jarvis_marketing_intake_state"


def _payload_from_state(st: Any) -> dict[str, Any]:
    return {
        "pending_secret_key": st.pending_secret_key,
        "pending_secret_label": st.pending_secret_label,
        "pending_secret_type": st.pending_secret_type,
        "pending_secret_env_var": st.pending_secret_env_var,
        "pending_secret_phase": st.pending_secret_phase,
        "pending_pipeline_to_resume": st.pending_pipeline_to_resume,
        "pending_pipeline_args": dict(st.pending_pipeline_args or {}),
        "secret_intake_started_at": st.secret_intake_started_at,
        "secret_intake_last_activity_at": st.secret_intake_last_activity_at,
        "secret_runtime_env_path": st.secret_runtime_env_path,
    }


def _apply_payload_to_state(st: Any, payload: dict[str, Any]) -> None:
    st.pending_secret_key = payload.get("pending_secret_key")
    st.pending_secret_label = payload.get("pending_secret_label")
    st.pending_secret_type = payload.get("pending_secret_type")
    st.pending_secret_env_var = payload.get("pending_secret_env_var")
    st.pending_secret_phase = str(payload.get("pending_secret_phase") or "")
    st.pending_pipeline_to_resume = payload.get("pending_pipeline_to_resume")
    raw_args = payload.get("pending_pipeline_args")
    st.pending_pipeline_args = dict(raw_args) if isinstance(raw_args, dict) else {}
    try:
        st.secret_intake_started_at = (
            float(payload["secret_intake_started_at"])
            if payload.get("secret_intake_started_at") is not None
            else None
        )
    except (TypeError, ValueError):
        st.secret_intake_started_at = None
    try:
        st.secret_intake_last_activity_at = (
            float(payload["secret_intake_last_activity_at"])
            if payload.get("secret_intake_last_activity_at") is not None
            else None
        )
    except (TypeError, ValueError):
        st.secret_intake_last_activity_at = None
    st.secret_runtime_env_path = payload.get("secret_runtime_env_path")


def delete_marketing_intake_state(chat_id: str, user_id: str) -> None:
    from sqlalchemy import text

    from app.database import engine, ensure_jarvis_marketing_intake_table

    if engine is None:
        return
    if not ensure_jarvis_marketing_intake_table(engine):
        return
    c = (chat_id or "").strip()
    u = (user_id or "").strip()
    if not c or not u:
        return
    try:
        with engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {_TABLE} WHERE chat_id = :c AND user_id = :u"),
                {"c": c, "u": u},
            )
    except Exception as e:
        logger.warning("jarvis.marketing_intake_db.delete_failed err=%s", type(e).__name__)


def upsert_marketing_intake_state(chat_id: str, user_id: str, st: Any) -> None:
    from sqlalchemy import text

    from app.database import engine, ensure_jarvis_marketing_intake_table
    from app.jarvis.dialog_state import _secret_flow_active

    if engine is None:
        return
    if not _secret_flow_active(st):
        return
    if not ensure_jarvis_marketing_intake_table(engine):
        return
    c = (chat_id or "").strip()
    u = (user_id or "").strip()
    if not c or not u:
        return
    body = json.dumps(_payload_from_state(st), separators=(",", ":"), sort_keys=True)
    try:
        with engine.begin() as conn:
            if conn.engine.dialect.name == "sqlite":
                conn.execute(
                    text(
                        f"""
                        INSERT INTO {_TABLE} (chat_id, user_id, payload, updated_at)
                        VALUES (:c, :u, :p, CURRENT_TIMESTAMP)
                        ON CONFLICT(chat_id, user_id) DO UPDATE SET
                            payload = excluded.payload,
                            updated_at = CURRENT_TIMESTAMP
                        """
                    ),
                    {"c": c, "u": u, "p": body},
                )
            else:
                conn.execute(
                    text(
                        f"""
                        INSERT INTO {_TABLE} (chat_id, user_id, payload, updated_at)
                        VALUES (:c, :u, :p, NOW())
                        ON CONFLICT (chat_id, user_id) DO UPDATE SET
                            payload = EXCLUDED.payload,
                            updated_at = NOW()
                        """
                    ),
                    {"c": c, "u": u, "p": body},
                )
    except Exception as e:
        logger.warning("jarvis.marketing_intake_db.upsert_failed err=%s", type(e).__name__)


def try_hydrate_secret_intake_from_db(chat_id: str, user_id: str) -> None:
    """Load persisted intake into in-memory store when the process has no active secret flow."""
    from sqlalchemy import text

    from app.database import engine, ensure_jarvis_marketing_intake_table
    from app.jarvis.dialog_state import (
        DialogState,
        _secret_flow_active,
        _secret_intake_ttl_seconds,
        _store,
        dialog_key,
        set_state,
    )

    if engine is None:
        return
    if not ensure_jarvis_marketing_intake_table(engine):
        return

    key = dialog_key(chat_id, user_id)
    st_mem = _store.get(key)
    if st_mem is not None and _secret_flow_active(st_mem):
        return

    c = (chat_id or "").strip()
    u = (user_id or "").strip()
    if not c or not u:
        return

    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(f"SELECT payload FROM {_TABLE} WHERE chat_id = :c AND user_id = :u LIMIT 1"),
                {"c": c, "u": u},
            ).fetchone()
    except Exception as e:
        logger.warning("jarvis.marketing_intake_db.load_failed err=%s", type(e).__name__)
        return

    if row is None:
        return
    raw_p = row[0]
    try:
        payload = json.loads(raw_p) if isinstance(raw_p, str) else json.loads(str(raw_p))
    except (TypeError, ValueError, json.JSONDecodeError):
        delete_marketing_intake_state(c, u)
        return

    if not isinstance(payload, dict):
        delete_marketing_intake_state(c, u)
        return

    base = payload.get("secret_intake_last_activity_at") or payload.get("secret_intake_started_at")
    try:
        base_f = float(base) if base is not None else 0.0
    except (TypeError, ValueError):
        base_f = 0.0
    if base_f <= 0.0 or time.time() > base_f + _secret_intake_ttl_seconds():
        delete_marketing_intake_state(c, u)
        logger.info("jarvis.marketing_intake_db.hydrate_skip reason=expired chat_id=%s", c)
        return

    st = st_mem if st_mem is not None else DialogState()
    _apply_payload_to_state(st, payload)
    if not _secret_flow_active(st):
        delete_marketing_intake_state(c, u)
        return

    set_state(c, u, st)
    logger.info("jarvis.marketing_intake_db.hydrated chat_id=%s user_id=%s", c, u)
