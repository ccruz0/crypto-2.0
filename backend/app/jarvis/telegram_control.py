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

_TELEGRAM_MAX_LEN = 4000

_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}

_SOURCE_FRIENDLY = {
    "google_search_console": "Google Search Console",
    "ga4": "Google Analytics",
    "google_ads": "Google Ads",
    "ga4_top_pages": "Google Analytics",
    "marketing": "Marketing",
    "marketing_source_status": "Marketing sources",
    "ops": "Operations",
}


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


def _telegram_clip(text: str, max_len: int = _TELEGRAM_MAX_LEN) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _jarvis_result_has_executor_error(res: dict[str, Any]) -> bool:
    """True when :func:`execute_plan` / :func:`invoke_registered_tool` returned a failure dict."""
    return res.get("error") is not None


def _looks_like_run_marketing_review_result(res: dict[str, Any]) -> bool:
    """Shape match for :func:`run_marketing_review` when plan.action is missing or mismatched."""
    if res.get("tool") == "run_marketing_review":
        return True
    return (
        "analysis_status" in res
        and "proposal_status" in res
        and "top_findings" in res
        and "proposed_actions" in res
        and "summary" in res
    )


def _unavailable_source_labels(res: dict[str, Any]) -> list[str]:
    raw = res.get("unavailable_sources") or []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw[:10]:
        if not isinstance(x, str) or not x.strip():
            continue
        key = x.strip()
        out.append(_SOURCE_FRIENDLY.get(key, key.replace("_", " ").title()))
    seen: set[str] = set()
    deduped: list[str] = []
    for s in out:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped


def _priority_bracket(priority: str | None) -> str:
    p = (priority or "medium").strip().lower()
    if p not in ("high", "medium", "low"):
        p = "medium"
    return f"[{p.upper()}]"


def _missing_line_bucket(line: str) -> str:
    """Group display lines that refer to the same marketing source (dedup Telegram output)."""
    sl = line.lower()
    if "google ads" in sl:
        return "ads"
    if "search console" in sl or "gsc" in sl:
        return "gsc"
    if (
        "google analytics" in sl
        or " ga4" in sl
        or sl.startswith("ga4")
        or ("analytics" in sl and "google" in sl)
    ):
        return "ga"
    return f"other:{line}"


def _missing_line_priority(line: str) -> int:
    """Higher = prefer this line when collapsing duplicates for the same :func:`_missing_line_bucket`."""
    sl = line.lower()
    if sl.startswith("connect "):
        return 100
    if "configure ga4" in sl or ("configure" in sl and "booking" in sl):
        return 95
    if " not configured" in sl:
        return 85
    if "data not available" in sl:
        return 50
    if len(line) <= 40 and line.count(" ") <= 4:
        return 30
    return 45


def _dedupe_missing_display_lines(lines: list[str]) -> list[str]:
    """
    Collapse overlapping missing-source lines (e.g. ``unavailable_sources`` short labels vs
    missing-data titles) into one executive line per source bucket.
    """
    buckets_order: list[str] = []
    best: dict[str, tuple[int, str]] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        b = _missing_line_bucket(line)
        pr = _missing_line_priority(line)
        if b not in best:
            buckets_order.append(b)
            best[b] = (pr, line)
            continue
        old_pr, old_line = best[b]
        if pr > old_pr:
            best[b] = (pr, line)
        elif pr == old_pr and len(line) < len(old_line):
            best[b] = (pr, line)
    return [best[b][1] for b in buckets_order]


def _missing_data_bullets(missing: list[Any]) -> list[str]:
    lines: list[str] = []
    for m in missing[:20]:
        if not isinstance(m, dict):
            continue
        title = str(m.get("title") or "").strip()
        src = str(m.get("source") or "").strip()
        if title:
            lines.append(title)
        elif src:
            lines.append(_SOURCE_FRIENDLY.get(src, src.replace("_", " ").title()))
    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


def _marketing_insufficient_fallback(res: dict[str, Any]) -> str:
    missing = list(res.get("missing_data") or [])
    bullets = _missing_data_bullets(missing)
    if not bullets:
        bullets = [
            "Google Analytics",
            "Google Ads",
            "Google Search Console",
        ]
    body = "⚠️ Not enough data to analyze marketing yet.\n\nMissing:\n"
    body += "\n".join(f"• {b}" for b in bullets[:12])
    return _telegram_clip(body)


def _format_analyze_marketing_opportunities_telegram(res: dict[str, Any]) -> str:
    if res.get("status") == "unavailable":
        msg = str(res.get("message") or res.get("reason") or "Marketing analysis unavailable.")
        detail = str(res.get("detail") or "").strip()
        if detail:
            msg = f"{msg}\n{detail[:600]}"
        return _telegram_clip(f"⚠️ {msg}")

    opps: list[dict[str, Any]] = []
    for key in ("biggest_opportunities", "conversion_gaps"):
        for item in res.get(key) or []:
            if isinstance(item, dict):
                opps.append(item)

    def _opp_sort_key(d: dict[str, Any]) -> tuple[int, str]:
        pr = str(d.get("priority") or "medium").lower()
        return (_PRIORITY_ORDER.get(pr, 1), str(d.get("title") or ""))

    opps.sort(key=_opp_sort_key)
    opps = opps[:5]

    wastes_raw = res.get("biggest_wastes") or []
    wastes: list[dict[str, Any]] = [w for w in wastes_raw if isinstance(w, dict)][:5]

    missing_raw = res.get("missing_data") or []
    missing_items: list[dict[str, Any]] = [m for m in missing_raw if isinstance(m, dict)][:5]

    has_body = bool(opps or wastes or missing_items)
    overall = str(res.get("status") or "")
    if not has_body and overall == "insufficient_data":
        return _marketing_insufficient_fallback(res)

    lines: list[str] = ["🧠 Marketing Analysis", ""]

    if opps:
        lines.append("Top Opportunities:")
        for o in opps:
            pr = _priority_bracket(str(o.get("priority")))
            title = str(o.get("title") or "(untitled)").strip()
            summary = str(o.get("summary") or "").strip()
            lines.append(f"• {pr} {title}")
            if summary:
                lines.append(f"  {summary}")
        lines.append("")

    if wastes:
        lines.append("Wasted Spend:")
        for w in wastes:
            camp = w.get("campaign")
            page = w.get("page")
            head = ""
            if camp:
                head = str(camp).strip()
            elif page:
                head = str(page).strip()
            else:
                head = str(w.get("title") or "Campaign").strip()
            reason = str(w.get("summary") or w.get("title") or "").strip()
            lines.append(f"• {head}")
            if reason:
                lines.append(f"  {reason}")
        lines.append("")

    if missing_items:
        lines.append("Missing Data:")
        for m in missing_items:
            label = str(m.get("title") or m.get("summary") or "Item").strip()
            lines.append(f"• {label}")
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()
    if len(lines) <= 1:
        return _marketing_insufficient_fallback(res)

    return _telegram_clip("\n".join(lines))


def _format_propose_marketing_actions_telegram(res: dict[str, Any]) -> str:
    if res.get("status") == "unavailable":
        msg = str(res.get("message") or res.get("reason") or "Action proposals unavailable.")
        detail = str(res.get("detail") or "").strip()
        if detail:
            msg = f"{msg}\n{detail[:600]}"
        return _telegram_clip(f"⚠️ {msg}")

    actions_raw = res.get("proposed_actions") or []
    actions: list[dict[str, Any]] = [a for a in actions_raw if isinstance(a, dict)]

    def _act_sort_key(d: dict[str, Any]) -> tuple[int, str]:
        pr = str(d.get("priority") or "medium").lower()
        return (_PRIORITY_ORDER.get(pr, 1), str(d.get("title") or ""))

    actions.sort(key=_act_sort_key)
    actions = actions[:5]

    if not actions:
        return _marketing_insufficient_fallback(res)

    lines: list[str] = ["🚀 Recommended Actions", ""]
    for i, a in enumerate(actions, start=1):
        pr = _priority_bracket(str(a.get("priority")))
        title = str(a.get("title") or "(untitled)").strip()
        target = str(a.get("target") or "").strip() or "—"
        why = str(a.get("reason") or a.get("summary") or "").strip() or "—"
        lines.append(f"{i}. {pr} {title}")
        lines.append(f"Target: {target}")
        lines.append(f"Why: {why}")
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()

    return _telegram_clip("\n".join(lines))


def _format_run_marketing_review_error_telegram(res: dict[str, Any]) -> str:
    """Short runtime error for executor/tool failures (no JSON, no docs)."""
    err = res.get("error")
    detail = str(res.get("detail") or "").strip()
    msg = str(res.get("message") or "").strip()
    parts: list[str] = ["⚠️ Marketing review failed"]
    if err:
        parts.append(f"({err})")
    if detail:
        parts.append(detail[:400])
    elif msg:
        parts.append(msg[:300])
    return _telegram_clip(" ".join(parts).strip())


def _format_run_marketing_review_telegram(res: dict[str, Any]) -> str:
    if _jarvis_result_has_executor_error(res):
        return _format_run_marketing_review_error_telegram(res)

    if res.get("status") == "unavailable":
        msg = str(res.get("message") or res.get("reason") or "Marketing review unavailable.")
        detail = str(res.get("detail") or "").strip()
        if detail:
            msg = f"{msg}\n{detail[:400]}"
        return _telegram_clip(f"⚠️ {msg}")

    summary = str(res.get("summary") or "").strip()
    st = str(res.get("status") or "")

    findings_raw = res.get("top_findings") or []
    findings: list[dict[str, Any]] = [f for f in findings_raw if isinstance(f, dict)][:5]

    def _prio_key(d: dict[str, Any]) -> tuple[int, str]:
        pr = str(d.get("priority") or "medium").lower()
        return (_PRIORITY_ORDER.get(pr, 1), str(d.get("title") or ""))

    findings.sort(key=_prio_key)

    proposed_raw = res.get("proposed_actions") or []
    proposed: list[dict[str, Any]] = [p for p in proposed_raw if isinstance(p, dict)]

    def _proposed_sort_key(d: dict[str, Any]) -> tuple[int, int, str]:
        pr = str(d.get("priority") or "medium").lower()
        t = str(d.get("title") or "")
        setup_first = 0 if (t.startswith("Connect ") or "Configure GA4" in t) else 1
        return (setup_first, _PRIORITY_ORDER.get(pr, 1), t)

    proposed.sort(key=_proposed_sort_key)
    proposed = proposed[:5]

    staged_raw = res.get("staged_actions") or []
    staged_titles: list[str] = []
    if isinstance(staged_raw, list):
        for s in staged_raw[:5]:
            if isinstance(s, dict):
                t = str(s.get("title") or "").strip()
                if t:
                    staged_titles.append(t)

    missing_bullets = _missing_data_bullets(list(res.get("missing_data") or []))
    src_labels = _unavailable_source_labels(res)
    missing_combined = _dedupe_missing_display_lines(missing_bullets + src_labels)[:5]

    limited = (
        st in ("insufficient_data", "partial")
        or (not findings and not proposed)
    )

    if not summary and limited:
        summary = "Marketing review completed with limited data."
    elif not summary:
        summary = "Marketing review completed."

    lines: list[str] = ["🧠 Marketing Review", "", "Summary:", summary, ""]

    if findings:
        lines.append("Top Findings:")
        for f in findings:
            pr = _priority_bracket(str(f.get("priority")))
            title = str(f.get("title") or "").strip() or "(untitled)"
            lines.append(f"• {pr} {title}")
        lines.append("")

    if proposed:
        lines.append("Proposed Actions:")
        for p in proposed:
            pr = _priority_bracket(str(p.get("priority")))
            title = str(p.get("title") or "").strip() or "(untitled)"
            lines.append(f"• {pr} {title}")
        lines.append("")

    if staged_titles:
        lines.append("Staged:")
        for t in staged_titles:
            lines.append(f"• {t}")
        lines.append("")

    if missing_combined:
        lines.append("Missing Data:")
        for m in missing_combined:
            lines.append(f"• {m}")

    while lines and lines[-1] == "":
        lines.pop()

    return _telegram_clip("\n".join(lines))


def format_compact_jarvis_reply(kind: str, payload: dict[str, Any]) -> str:
    """Short Telegram-safe text (no huge JSON)."""
    if kind == "jarvis":
        rid = str(payload.get("jarvis_run_id") or "")
        res = payload.get("result")
        plan = payload.get("plan") or {}
        action = ""
        if isinstance(plan, dict):
            action = str(plan.get("action") or "").strip()

        review_fmt = action == "run_marketing_review" or (
            isinstance(res, dict) and _looks_like_run_marketing_review_result(res)
        )
        shape_fallback = bool(
            review_fmt
            and isinstance(res, dict)
            and action != "run_marketing_review"
            and _looks_like_run_marketing_review_result(res)
        )
        if review_fmt:
            if not isinstance(res, dict):
                logger.info(
                    "jarvis.telegram.format run_id=%s route=run_marketing_review plan_action=%s "
                    "result_status=None shape_fallback=%s keys=None",
                    rid or "-",
                    action or "-",
                    int(shape_fallback),
                )
                body = "⚠️ Marketing review: no result payload returned."
                if rid:
                    body = _telegram_clip(f"{body}\n\nrun {rid}")
                return _telegram_clip(body)
            logger.info(
                "jarvis.telegram.format run_id=%s route=run_marketing_review plan_action=%s "
                "result_status=%s shape_fallback=%s keys=%s",
                rid or "-",
                action or "-",
                res.get("status"),
                int(shape_fallback),
                list(res.keys()),
            )
            body = _format_run_marketing_review_telegram(res)
            if rid:
                body = _telegram_clip(f"{body}\n\nrun {rid}")
            return body

        if isinstance(res, dict) and not _jarvis_result_has_executor_error(res):
            if action == "analyze_marketing_opportunities":
                logger.info(
                    "jarvis.telegram.format run_id=%s route=analyze_marketing_opportunities "
                    "plan_action=%s result_status=%s shape_fallback=0 keys=%s",
                    rid or "-",
                    action,
                    res.get("status"),
                    list(res.keys()),
                )
                body = _format_analyze_marketing_opportunities_telegram(res)
                if rid:
                    body = _telegram_clip(f"{body}\n\nrun {rid}")
                return body
            if action == "propose_marketing_actions":
                logger.info(
                    "jarvis.telegram.format run_id=%s route=propose_marketing_actions "
                    "plan_action=%s result_status=%s shape_fallback=0 keys=%s",
                    rid or "-",
                    action,
                    res.get("status"),
                    list(res.keys()),
                )
                body = _format_propose_marketing_actions_telegram(res)
                if rid:
                    body = _telegram_clip(f"{body}\n\nrun {rid}")
                return body

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
        rk = list(res.keys()) if isinstance(res, dict) else None
        logger.info(
            "jarvis.telegram.format run_id=%s route=generic plan_action=%s result_status=%s shape_fallback=0 keys=%s",
            rid or "-",
            action or "-",
            (res.get("status") or res.get("error")) if isinstance(res, dict) else None,
            rk,
        )
        return _telegram_clip(msg)

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
