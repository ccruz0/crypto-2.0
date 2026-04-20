"""Notion-backed mission persistence for autonomous Jarvis."""

from __future__ import annotations

import logging
import os
import json
from datetime import datetime, timezone
from typing import Any

import httpx

from app.jarvis.autonomous_schemas import (
    MISSION_STATUS_RECEIVED,
    can_transition_mission,
)
from app.jarvis.notion_mission_readability import (
    format_executive_summary_block,
    format_timeline_line,
    human_mission_status,
)
from app.services.notion_task_reader import get_notion_task_by_id
from app.services.notion_tasks import create_notion_task

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _api_key() -> str:
    env_key = (os.getenv("NOTION_API_KEY") or "").strip()
    if env_key:
        return env_key
    try:
        from app.core.config import settings

        return str(getattr(settings, "NOTION_API_KEY", "") or "").strip()
    except Exception:
        return ""


class NotionMissionService:
    """Persists mission state/output directly in Notion pages."""

    def __init__(self) -> None:
        self._api_key = _api_key()

    def configured(self) -> bool:
        return bool(self._api_key)

    def create_mission(
        self,
        *,
        prompt: str,
        actor: str,
        specialist_agent: str | None = None,
        operator_short_prompt: str | None = None,
    ) -> dict[str, Any]:
        if (specialist_agent or "").strip().lower() == "perico":
            op = (operator_short_prompt or prompt).strip()
            title = f"Perico: {op[:96]}".strip() or "Perico: (sin texto)"
            details = (
                "Misión Jarvis — especialista Perico (software)\n\n"
                f"Actor: {actor or 'desconocido'}\n"
                f"Creada: {_utc_now_iso()}\n"
                f"Petición del operador:\n{op[:900]}\n\n"
                f"Contexto ampliado (truncado):\n{prompt[:1500]}"
            )
        else:
            title = f"Misión: {prompt[:96]}".strip()
            details = (
                f"Misión Jarvis (autónoma)\n\n"
                f"Actor: {actor or 'desconocido'}\n"
                f"Creada: {_utc_now_iso()}\n"
                f"Petición:\n{prompt[:1500]}"
            )
        created = create_notion_task(
            title=title,
            project="Automation",
            type="automation",
            details=details,
            status="planned",
            source="jarvis-autonomous",
        )
        if not isinstance(created, dict) or not created.get("id"):
            raise RuntimeError("Failed to create Notion mission record")

        mission_id = str(created["id"])
        self._append_comment(
            mission_id,
            f"[MISSION_STATE] {MISSION_STATUS_RECEIVED} actor={actor or 'unknown'}",
        )
        self._set_mission_state_property(mission_id, MISSION_STATUS_RECEIVED)
        self.append_readability_executive_summary(
            mission_id,
            objective=prompt[:1200],
            status=human_mission_status(MISSION_STATUS_RECEIVED),
            what_jarvis_did="Misión creada en Notion y puesta en cola.",
            next_step="Jarvis lanzará el planificador y seguirá el flujo.",
        )
        self.append_readability_timeline(mission_id, "Misión registrada en Notion.")
        return {
            "mission_id": mission_id,
            "status": MISSION_STATUS_RECEIVED,
            "url": created.get("url"),
        }

    def get_mission(self, mission_id: str) -> dict[str, Any] | None:
        raw = get_notion_task_by_id(mission_id)
        if not isinstance(raw, dict):
            return None
        return {
            "mission_id": str(raw.get("id") or mission_id),
            "status": str(raw.get("status") or "").strip().lower() or MISSION_STATUS_RECEIVED,
            "task": str(raw.get("task") or ""),
            "details": str(raw.get("details") or ""),
            "source": str(raw.get("source") or ""),
        }

    def transition_state(self, mission_id: str, *, to_state: str, note: str = "") -> bool:
        mission = self.get_mission(mission_id)
        if mission is None:
            return False
        from_state = str(mission.get("status") or "").strip() or MISSION_STATUS_RECEIVED
        if from_state != to_state and not can_transition_mission(from_state, to_state):
            logger.warning(
                "jarvis.autonomous.invalid_transition mission_id=%s from=%s to=%s",
                mission_id,
                from_state,
                to_state,
            )
            return False
        self._set_mission_state_property(mission_id, to_state)
        suffix = f" note={note}" if note else ""
        self._append_comment(mission_id, f"[MISSION_STATE] {to_state}{suffix}")
        return True

    def append_agent_output(self, mission_id: str, *, agent_name: str, content: str) -> None:
        body = (content or "").strip()
        if not body:
            return
        normalized = self._normalize_action_fields(body)
        self._append_comment(mission_id, f"[AGENT_OUTPUT:{agent_name}] {normalized[:1800]}")
        if agent_name == "ops":
            self.append_ops_diagnostics(mission_id, normalized)
            self.append_ops_fix_proposal(mission_id, normalized)

    def append_event(self, mission_id: str, *, event: str, detail: str = "") -> None:
        msg = f"[MISSION_EVENT] {event}"
        if detail:
            msg = f"{msg} :: {detail}"
        self._append_comment(mission_id, msg[:1900])

    def append_pending_approval_payload(self, mission_id: str, *, actions: list[dict[str, Any]]) -> None:
        """Persist structured actions awaiting Telegram approval (read back on approve)."""
        rows = [a for a in actions if isinstance(a, dict)][:5]
        if not rows:
            return
        payload = {"version": 1, "actions": rows}
        try:
            body = json.dumps(payload, ensure_ascii=True)[:1600]
        except Exception:
            body = "{}"
        self._append_comment(mission_id, f"[PENDING_APPROVAL_ACTIONS] {body}")

    def get_latest_pending_approval_actions(self, mission_id: str) -> list[dict[str, Any]]:
        """Best-effort: scan Notion page blocks for the last [PENDING_APPROVAL_ACTIONS] JSON."""
        if not self._api_key:
            return []
        texts: list[str] = []
        cursor: str | None = None
        try:
            with httpx.Client(timeout=15.0) as client:
                while True:
                    url = f"{NOTION_API_BASE}/blocks/{mission_id}/children?page_size=100"
                    if cursor:
                        url = f"{url}&start_cursor={cursor}"
                    resp = client.get(url, headers=_headers(self._api_key))
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    for block in data.get("results") or []:
                        if not isinstance(block, dict):
                            continue
                        t = self._block_plain_text(block)
                        if t:
                            texts.append(t)
                    if not data.get("has_more"):
                        break
                    cursor = data.get("next_cursor")
                    if not cursor:
                        break
        except Exception as exc:
            logger.debug("jarvis.pending_approval_fetch_failed mission_id=%s err=%s", mission_id, exc)
            return []
        last_payload: dict[str, Any] | None = None
        for line in texts:
            idx = line.find("[PENDING_APPROVAL_ACTIONS]")
            if idx < 0:
                continue
            raw = line[idx + len("[PENDING_APPROVAL_ACTIONS]") :].strip()
            try:
                last_payload = json.loads(raw)
            except Exception:
                continue
        if not isinstance(last_payload, dict):
            return []
        acts = last_payload.get("actions")
        if not isinstance(acts, list):
            return []
        return [x for x in acts if isinstance(x, dict)]

    def _block_plain_text(self, block: dict[str, Any]) -> str:
        for key in ("paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item"):
            node = block.get(key)
            if not isinstance(node, dict):
                continue
            parts: list[str] = []
            for rt in node.get("rich_text") or []:
                if not isinstance(rt, dict):
                    continue
                parts.append(str(rt.get("plain_text") or ""))
            return "".join(parts).strip()
        return ""

    def append_action_baseline(self, mission_id: str, *, action: dict[str, Any]) -> None:
        payload = {
            "action_title": str(action.get("title") or "").strip(),
            "action_type": str(action.get("action_type") or "analysis"),
            "execution_mode": str(action.get("execution_mode") or "unknown"),
            "priority_score": int(action.get("priority_score", 0) or 0),
            "expected_impact": str(action.get("impact") or "medium"),
            "baseline_metrics": self._capture_metrics_snapshot(),
            "captured_at": _utc_now_iso(),
        }
        self._append_comment(mission_id, f"[ACTION_BASELINE] {json.dumps(payload, ensure_ascii=True)[:1800]}")

    def append_readability_executive_summary(
        self,
        mission_id: str,
        *,
        objective: str = "",
        status: str = "",
        what_jarvis_did: str = "",
        key_result: str = "",
        blocked: str = "",
        next_step: str = "",
    ) -> None:
        """Operator-facing summary block; does not replace technical [AGENT_OUTPUT] logs."""
        body = format_executive_summary_block(
            objective=objective,
            status=status,
            what_jarvis_did=what_jarvis_did,
            key_result=key_result,
            blocked=blocked,
            next_step=next_step,
        )
        if body.strip():
            self._append_comment(mission_id, body)

    def append_readability_timeline(self, mission_id: str, sentence: str) -> None:
        line = format_timeline_line(sentence)
        if line:
            self._append_comment(mission_id, line)

    def append_technical_detail_marker(self, mission_id: str, title: str = "Detalle técnico") -> None:
        """Marks where raw agent/JSON logs live (append-only; fold in Notion UI manually)."""
        t = (title or "Detalle técnico").strip()[:120]
        self._append_comment(
            mission_id,
            f"[TECHNICAL_DETAIL] {t} — abajo quedan salidas de agentes y bloques JSON etiquetados.",
        )

    def append_outcome_evaluation(
        self,
        mission_id: str,
        *,
        evaluations: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> None:
        data = {
            "evaluations": evaluations,
            "summary": summary,
            "evaluated_at": _utc_now_iso(),
        }
        self._append_comment(mission_id, f"[ACTION_OUTCOMES] {json.dumps(data, ensure_ascii=True)[:1800]}")

    def get_recent_outcomes(self, mission_id: str, *, limit: int = 25) -> list[dict[str, Any]]:
        """
        Best-effort outcome memory extraction from Notion task details/comments.
        We read task details text as a fallback memory source and parse tagged lines.
        """
        mission = self.get_mission(mission_id) or {}
        details = str(mission.get("details") or "")
        if not details:
            return []
        out: list[dict[str, Any]] = []
        for line in details.splitlines():
            line = line.strip()
            if not line.startswith("[ACTION_OUTCOME_MEMORY]"):
                continue
            raw = line[len("[ACTION_OUTCOME_MEMORY]") :].strip()
            try:
                row = json.loads(raw)
            except Exception:
                continue
            if isinstance(row, dict):
                out.append(row)
            if len(out) >= limit:
                break
        return out

    def _set_mission_state_property(self, mission_id: str, state: str) -> None:
        if not self._api_key:
            return
        payloads = (
            {"properties": {"Status": {"rich_text": [{"type": "text", "text": {"content": state}}]}}},
            {"properties": {"Status": {"select": {"name": state}}}},
            {"properties": {"Status": {"status": {"name": state}}}},
        )
        with httpx.Client(timeout=10.0) as client:
            for payload in payloads:
                try:
                    resp = client.patch(
                        f"{NOTION_API_BASE}/pages/{mission_id}",
                        json=payload,
                        headers=_headers(self._api_key),
                    )
                except Exception:
                    continue
                if resp.status_code == 200:
                    return

    def _append_comment(self, mission_id: str, content: str) -> None:
        if not self._api_key:
            return
        line = f"[{_utc_now_iso()}] {content[:1800]}"
        payload = {
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": line},
                            }
                        ]
                    },
                }
            ]
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                client.patch(
                    f"{NOTION_API_BASE}/blocks/{mission_id}/children",
                    json=payload,
                    headers=_headers(self._api_key),
                )
        except Exception as exc:
            logger.debug("jarvis.autonomous.append_comment_failed mission_id=%s err=%s", mission_id, exc)

    def _normalize_action_fields(self, raw_content: str) -> str:
        """
        Ensure action payload comments include execution_mode and priority_score.
        Best-effort for JSON strategy/execution payloads.
        """
        text = (raw_content or "").strip()
        if not text:
            return text
        try:
            obj = json.loads(text)
        except Exception:
            return text
        if not isinstance(obj, dict):
            return text
        changed = False
        for key in (
            "actions",
            "executed",
            "waiting_for_approval",
            "waiting_for_input",
            "proposed_fixes",
            "auto_executed",
        ):
            rows = obj.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if "execution_mode" not in row:
                    row["execution_mode"] = "unknown"
                    changed = True
                if "priority_score" not in row:
                    row["priority_score"] = 0
                    changed = True
        if not changed:
            return text
        try:
            return json.dumps(obj, ensure_ascii=True)
        except Exception:
            return text

    def append_ops_diagnostics(self, mission_id: str, raw_content: str) -> None:
        try:
            obj = json.loads(raw_content)
        except Exception:
            return
        if not isinstance(obj, dict):
            return
        diagnostics = [x for x in (obj.get("diagnostics") or []) if isinstance(x, dict)]
        if not diagnostics:
            return
        payload = {"diagnostics": diagnostics[:12], "count": len(diagnostics), "captured_at": _utc_now_iso()}
        self._append_comment(mission_id, f"[OPS_DIAGNOSTICS] {json.dumps(payload, ensure_ascii=True)[:1800]}")

    def append_ops_fix_proposal(self, mission_id: str, raw_content: str) -> None:
        try:
            obj = json.loads(raw_content)
        except Exception:
            return
        if not isinstance(obj, dict):
            return
        proposed = [x for x in (obj.get("proposed_fixes") or []) if isinstance(x, dict)]
        waiting = [x for x in (obj.get("waiting_for_approval") or []) if isinstance(x, dict)]
        executed = [x for x in (obj.get("auto_executed") or []) if isinstance(x, dict)]
        payload = {
            "proposed_fixes": proposed[:10],
            "approval_needed": waiting[:10],
            "safe_inspections_executed": executed[:10],
            "captured_at": _utc_now_iso(),
        }
        if not proposed and not waiting and not executed:
            return
        self._append_comment(mission_id, f"[OPS_FIX_PROPOSALS] {json.dumps(payload, ensure_ascii=True)[:1800]}")

    def _capture_metrics_snapshot(self) -> dict[str, Any]:
        """
        Capture a minimal baseline snapshot now.
        Placeholder source for future real metric providers.
        """
        return {"timestamp": _utc_now_iso(), "score": 100.0}

