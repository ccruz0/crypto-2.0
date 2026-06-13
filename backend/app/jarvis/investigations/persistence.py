"""Persistence for jarvis_investigations (investigation memory)."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

from app.database import engine, ensure_jarvis_investigations_table
from app.jarvis.investigations.investigation_report import InvestigationReport
from app.jarvis.investigations.investigation_types import InvestigationStatus

logger = logging.getLogger(__name__)


def _serialize_evidence(evidence: list[dict[str, Any]]) -> str:
    return json.dumps(evidence, default=str)


def save_investigation(report: InvestigationReport) -> bool:
    if engine is None or not ensure_jarvis_investigations_table(engine):
        logger.warning("save_investigation: database unavailable")
        return False

    evidence_json = _serialize_evidence(report.evidence)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO jarvis_investigations (
                        investigation_id, objective, category, template_id, status,
                        summary, root_cause, confidence, evidence_json,
                        recommended_fix, impact, ranked_causes_json,
                        verification_steps_json, next_action, created_at
                    ) VALUES (
                        :investigation_id, :objective, :category, :template_id, :status,
                        :summary, :root_cause, :confidence, :evidence_json,
                        :recommended_fix, :impact, :ranked_causes_json,
                        :verification_steps_json, :next_action, :created_at
                    )
                    ON CONFLICT (investigation_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        summary = EXCLUDED.summary,
                        root_cause = EXCLUDED.root_cause,
                        confidence = EXCLUDED.confidence,
                        evidence_json = EXCLUDED.evidence_json,
                        recommended_fix = EXCLUDED.recommended_fix,
                        impact = EXCLUDED.impact,
                        ranked_causes_json = EXCLUDED.ranked_causes_json,
                        verification_steps_json = EXCLUDED.verification_steps_json,
                        next_action = EXCLUDED.next_action
                    """
                ),
                {
                    "investigation_id": report.investigation_id,
                    "objective": report.objective[:2000],
                    "category": report.category,
                    "template_id": report.template_id,
                    "status": report.status.value,
                    "summary": report.summary[:4000],
                    "root_cause": (report.root_cause or "")[:2000],
                    "confidence": report.confidence,
                    "evidence_json": evidence_json,
                    "recommended_fix": report.recommended_fix[:2000],
                    "impact": report.impact[:2000],
                    "ranked_causes_json": json.dumps(
                        [
                            {
                                "cause": c.cause,
                                "score": c.score,
                                "supporting_evidence": c.supporting_evidence,
                                "explanation": c.explanation,
                            }
                            for c in report.ranked_causes
                        ],
                        default=str,
                    ),
                    "verification_steps_json": json.dumps(report.verification_steps, default=str),
                    "next_action": report.next_action[:1000],
                    "created_at": report.created_at,
                },
            )
        return True
    except Exception as exc:
        logger.error("save_investigation failed: %s", exc, exc_info=True)
        return False


def _row_to_dict(row: Any) -> dict[str, Any]:
    mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    created_at = mapping.get("created_at")
    if created_at is not None and hasattr(created_at, "isoformat"):
        mapping["created_at"] = created_at.isoformat()
    evidence = mapping.get("evidence_json")
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except json.JSONDecodeError:
            evidence = []
    ranked = mapping.get("ranked_causes_json")
    if isinstance(ranked, str):
        try:
            ranked = json.loads(ranked)
        except json.JSONDecodeError:
            ranked = []
    verification = mapping.get("verification_steps_json")
    if isinstance(verification, str):
        try:
            verification = json.loads(verification)
        except json.JSONDecodeError:
            verification = []

    return {
        "investigation_id": mapping.get("investigation_id"),
        "objective": mapping.get("objective"),
        "category": mapping.get("category"),
        "template_id": mapping.get("template_id"),
        "status": mapping.get("status"),
        "summary": mapping.get("summary"),
        "root_cause": mapping.get("root_cause"),
        "confidence": float(mapping.get("confidence") or 0),
        "evidence": evidence or [],
        "evidence_count": len(evidence or []),
        "recommended_fix": mapping.get("recommended_fix"),
        "impact": mapping.get("impact"),
        "ranked_causes": ranked or [],
        "verification_steps": verification or [],
        "next_action": mapping.get("next_action"),
        "created_at": mapping.get("created_at"),
    }


def get_investigation(investigation_id: str) -> dict[str, Any] | None:
    if engine is None or not ensure_jarvis_investigations_table(engine):
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM jarvis_investigations WHERE investigation_id = :id"),
                {"id": investigation_id},
            ).fetchone()
        return _row_to_dict(row) if row else None
    except Exception as exc:
        logger.error("get_investigation failed: %s", exc)
        return None


def list_investigations(*, limit: int = 20) -> list[dict[str, Any]]:
    if engine is None or not ensure_jarvis_investigations_table(engine):
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT investigation_id, objective, status, root_cause, confidence,
                           evidence_json, recommended_fix, category, created_at
                    FROM jarvis_investigations
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).fetchall()
        results = []
        for row in rows:
            d = _row_to_dict(row)
            results.append(
                {
                    "investigation_id": d["investigation_id"],
                    "objective": d["objective"],
                    "status": d["status"],
                    "root_cause": d["root_cause"],
                    "confidence": d["confidence"],
                    "evidence_count": d["evidence_count"],
                    "recommended_fix": d.get("recommended_fix"),
                    "category": d.get("category"),
                    "created_at": d.get("created_at"),
                }
            )
        return results
    except Exception as exc:
        logger.error("list_investigations failed: %s", exc)
        return []


def search_investigations(query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    if engine is None or not ensure_jarvis_investigations_table(engine):
        return []
    q = f"%{(query or '').strip()}%"
    if q == "%%":
        return list_investigations(limit=limit)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT investigation_id, objective, status, root_cause, confidence,
                           evidence_json, recommended_fix, category, summary, created_at
                    FROM jarvis_investigations
                    WHERE objective ILIKE :q OR root_cause ILIKE :q OR summary ILIKE :q
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"q": q, "limit": limit},
            ).fetchall()
        return [_row_to_dict(row) for row in rows]
    except Exception as exc:
        # SQLite fallback without ILIKE
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT investigation_id, objective, status, root_cause, confidence,
                               evidence_json, recommended_fix, category, summary, created_at
                        FROM jarvis_investigations
                        WHERE objective LIKE :q OR root_cause LIKE :q OR summary LIKE :q
                        ORDER BY created_at DESC
                        LIMIT :limit
                        """
                    ),
                    {"q": q, "limit": limit},
                ).fetchall()
            return [_row_to_dict(row) for row in rows]
        except Exception as inner:
            logger.error("search_investigations failed: %s / %s", exc, inner)
            return []
