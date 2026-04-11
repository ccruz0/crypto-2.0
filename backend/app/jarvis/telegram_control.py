"""
Telegram control surface for Jarvis (thin layer over orchestrator + tools).

Uses the same bot token and polling loop as app.services.telegram_commands — this
module only handles routing and formatting, not getUpdates.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable

from app.jarvis.orchestrator import run_jarvis
from app.jarvis.tools import TOOL_SPECS

logger = logging.getLogger(__name__)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

SendFn = Callable[[str], Any]


def _truthy_env(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def is_jarvis_telegram_enabled() -> bool:
    return _truthy_env("JARVIS_TELEGRAM_ENABLED")


def jarvis_telegram_token_present() -> bool:
    return bool((os.getenv("TELEGRAM_BOT_TOKEN") or "").strip())


def _split_id_list(raw: str | None) -> set[str]:
    if not raw or not str(raw).strip():
        return set()
    out: set[str] = set()
    for chunk in re.split(r"[,;\s\n]+", str(raw).strip()):
        tid = chunk.strip()
        if tid:
            out.add(tid)
    return out


def jarvis_allowlists_configured() -> bool:
    """Both lists must be non-empty (fail closed)."""
    chats = (os.getenv("TELEGRAM_ALLOWED_CHAT_IDS") or "").strip()
    users = (os.getenv("TELEGRAM_ALLOWED_USER_IDS") or "").strip()
    return bool(chats and users)


def jarvis_telegram_allowed(chat_id: str, user_id: str) -> bool:
    if not jarvis_allowlists_configured():
        return False
    chats = _split_id_list(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS"))
    users = _split_id_list(os.getenv("TELEGRAM_ALLOWED_USER_IDS"))
    return str(chat_id) in chats and str(user_id) in users


def actor_from_telegram_user(from_user: dict[str, Any] | None) -> str:
    """Stable short string for audit (no PII beyond Telegram public username)."""
    if not from_user:
        return "unknown"
    uid = from_user.get("id")
    uname = (from_user.get("username") or "").strip()
    if uname:
        return f"@{uname}"
    first = (from_user.get("first_name") or "").strip()
    if first and uid is not None:
        return f"{first} (id:{uid})"
    if uid is not None:
        return f"id:{uid}"
    return "unknown"


def log_jarvis_telegram_startup_status() -> None:
    """One-line visibility at startup (no secrets)."""
    en = is_jarvis_telegram_enabled()
    tok = jarvis_telegram_token_present()
    wl = jarvis_allowlists_configured()
    logger.info(
        "JarvisTelegram: enabled=%s token_present=%s allowlists_configured=%s",
        en,
        tok,
        wl,
    )
    if en and not tok:
        logger.warning(
            "JarvisTelegram: JARVIS_TELEGRAM_ENABLED but TELEGRAM_BOT_TOKEN missing — control commands will not work until token is set",
        )
    if en and not wl:
        logger.warning(
            "JarvisTelegram: allowlists empty or incomplete — set non-empty TELEGRAM_ALLOWED_CHAT_IDS and TELEGRAM_ALLOWED_USER_IDS",
        )


def _normalize_command_text(text: str) -> str:
    t = (text or "").strip()
    if "@" in t and t.startswith("/"):
        try:
            t = re.sub(r"@\S+", "", t).strip() or t
        except Exception:
            t = t.split("@", 1)[0].strip()
    return t


def classify_jarvis_command(text: str) -> tuple[str, str] | None:
    """
    If ``text`` is a Jarvis control command, return (kind, args_string).
    Otherwise return None. Does not handle generic /status (no uuid).
    """
    t = _normalize_command_text(text)
    if not t.startswith("/"):
        return None
    parts = t.split(None, 2)
    cmd = (parts[0] or "").lower()
    rest1 = (parts[1] or "").strip() if len(parts) > 1 else ""

    if cmd == "/jarvis":
        tail = t[len("/jarvis") :].strip()
        return ("jarvis", tail)
    if cmd == "/pending":
        return ("pending", "")
    if cmd == "/status" and rest1:
        if _UUID_RE.match(rest1):
            tail = t[len("/status") :].strip()
            return ("approval_status", tail)
        return None
    if cmd == "/approve" and len(parts) >= 2:
        rid = parts[1].strip()
        reason = parts[2].strip() if len(parts) > 2 else ""
        return ("approve", f"{rid}\n{reason}".strip())
    if cmd == "/reject" and len(parts) >= 2:
        rid = parts[1].strip()
        reason = parts[2].strip() if len(parts) > 2 else ""
        return ("reject", f"{rid}\n{reason}".strip())
    if cmd == "/execute" and rest1:
        return ("execute", rest1.strip())
    return None


def format_compact_jarvis_reply(kind: str, payload: dict[str, Any]) -> str:
    """Short Telegram-safe text (no huge JSON)."""
    if kind == "jarvis":
        rid = str(payload.get("jarvis_run_id") or "")
        res = payload.get("result")
        plan = payload.get("plan") or {}
        action = ""
        if isinstance(plan, dict):
            action = str(plan.get("action") or "")
        status = None
        tool = None
        if isinstance(res, dict):
            status = res.get("status") or res.get("error")
            tool = res.get("tool") or res.get("action")
        parts_out = ["Jarvis"]
        if rid:
            parts_out.append(f"run={rid}")
        if action:
            parts_out.append(f"plan={action}")
        if status:
            parts_out.append(f"status={status}")
        if tool:
            parts_out.append(f"tool={tool}")
        msg = " | ".join(parts_out)
        detail = _format_result_snippet(res)
        if detail:
            msg = msg + "\n" + detail
        return msg[:4000]

    if kind == "pending":
        rows = payload.get("approvals") or []
        n = int(payload.get("count") or 0)
        lines: list[str] = [f"Pending: {n}"]
        for r in rows[:15]:
            if not isinstance(r, dict):
                continue
            rid = r.get("jarvis_run_id", "")
            ap = r.get("approval_status", "")
            ex = r.get("execution_status", "")
            tg = r.get("tool", "")
            lines.append(f"• {rid} | {ap} | exec={ex} | {tg}")
        return "\n".join(lines)[:4000]

    if kind == "approval_status":
        if not payload.get("found"):
            return "Status: not_found"
        a = payload.get("approval") or {}
        if not isinstance(a, dict):
            return "Status: invalid"
        rid = a.get("jarvis_run_id", "")
        ap = a.get("approval_status", "")
        ex = a.get("execution_status", "")
        tg = a.get("tool", "")
        rl = a.get("risk_level", "")
        parts = [f"run={rid}", f"approval={ap}", f"exec={ex}", f"tool={tg}"]
        if rl:
            parts.append(f"risk={rl}")
        return " | ".join(str(p) for p in parts if p)[:4000]

    if kind in ("approve", "reject", "execute"):
        st = payload.get("status")
        out = [f"status={st}"]
        if payload.get("jarvis_run_id"):
            out.append(f"run={payload.get('jarvis_run_id')}")
        if payload.get("approval_status"):
            out.append(f"approval={payload.get('approval_status')}")
        if payload.get("execution_status"):
            out.append(f"exec={payload.get('execution_status')}")
        if payload.get("message") and st not in ("ok",):
            out.append(str(payload.get("message"))[:500])
        return " | ".join(out)[:4000]

    return str(payload)[:4000]


def _format_result_snippet(res: Any) -> str:
    if res is None:
        return ""
    if isinstance(res, dict):
        if res.get("error"):
            return f"error={res.get('error')} {res.get('detail', '')}"[:800]
        if res.get("status"):
            s = f"status={res.get('status')}"
            if res.get("message"):
                s += f" msg={str(res.get('message'))[:200]}"
            return s
        # small dict: echo keys
        if len(str(res)) < 400:
            return str(res)
        return "(result omitted; large)"
    if isinstance(res, str):
        return res[:500]
    return str(res)[:500]


def dispatch_jarvis_command(kind: str, args: str, *, actor: str) -> tuple[str, dict[str, Any]]:
    """
    Run Jarvis control action. Returns (kind_for_formatter, result_dict).
    """
    if kind == "jarvis":
        out = run_jarvis((args or "").strip())
        return ("jarvis", dict(out))

    if kind == "pending":
        fn = TOOL_SPECS["list_pending_approvals"].fn
        data = fn(limit=20)
        return ("pending", dict(data))

    if kind == "approval_status":
        rid = (args or "").strip().split()[0] if args else ""
        fn = TOOL_SPECS["get_approval_status"].fn
        data = fn(jarvis_run_id=rid)
        return ("approval_status", dict(data))

    if kind == "approve":
        lines = (args or "").split("\n", 1)
        rid = (lines[0] or "").strip()
        reason = (lines[1] or "").strip() if len(lines) > 1 else ""
        fn = TOOL_SPECS["approve_pending_action"].fn
        data = fn(jarvis_run_id=rid, reason=reason, actor=actor)
        return ("approve", dict(data))

    if kind == "reject":
        lines = (args or "").split("\n", 1)
        rid = (lines[0] or "").strip()
        reason = (lines[1] or "").strip() if len(lines) > 1 else ""
        fn = TOOL_SPECS["reject_pending_action"].fn
        data = fn(jarvis_run_id=rid, reason=reason, actor=actor)
        return ("reject", dict(data))

    if kind == "execute":
        rid = (args or "").strip()
        fn = TOOL_SPECS["execute_ready_action"].fn
        data = fn(jarvis_run_id=rid, actor=actor)
        return ("execute", dict(data))

    return ("unknown", {"error": "unknown_kind", "kind": kind})


def maybe_handle_jarvis_telegram_message(
    *,
    raw_text: str,
    chat_id: str,
    actor_user_id: str,
    from_user: dict[str, Any] | None,
    send: SendFn,
) -> bool:
    """
    If this is a Jarvis Telegram command, validate config/allowlist, run, reply.

    Returns True if the update was consumed (caller should return).
    """
    classified = classify_jarvis_command(raw_text)
    if classified is None:
        return False

    if not is_jarvis_telegram_enabled():
        send("Jarvis Telegram control is disabled (JARVIS_TELEGRAM_ENABLED).")
        return True

    if not jarvis_telegram_token_present():
        logger.warning("JarvisTelegram: command ignored — TELEGRAM_BOT_TOKEN missing")
        send("Jarvis Telegram is misconfigured: missing TELEGRAM_BOT_TOKEN.")
        return True

    if not jarvis_allowlists_configured():
        logger.warning("JarvisTelegram: allowlists not configured")
        send(
            "Jarvis Telegram: configure non-empty TELEGRAM_ALLOWED_CHAT_IDS and TELEGRAM_ALLOWED_USER_IDS.",
        )
        return True

    if not jarvis_telegram_allowed(chat_id, actor_user_id):
        logger.info(
            "JarvisTelegram: denied chat_id=%s user_id=%s",
            chat_id,
            actor_user_id,
        )
        send("⛔ Jarvis: chat or user not allowlisted.")
        return True

    kind, args = classified
    actor = actor_from_telegram_user(from_user)
    try:
        fmt_kind, payload = dispatch_jarvis_command(kind, args, actor=actor)
        text = format_compact_jarvis_reply(fmt_kind, payload)
        send(text)
    except Exception as e:
        logger.exception("JarvisTelegram: dispatch failed: %s", e)
        send(f"❌ Jarvis error: {e!s}"[:500])
    return True
