"""Structured evidence model for production diagnostic investigations."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

ConfidenceLevel = Literal["high", "medium", "low"]

CONFIDENCE_WEIGHTS: dict[str, float] = {
    "high": 1.0,
    "medium": 0.6,
    "low": 0.3,
}


class EvidenceItem(TypedDict):
    source: str
    reference: str
    detail: str
    confidence: ConfidenceLevel


def normalize_evidence(raw: Any) -> EvidenceItem | None:
    """Normalize a loose dict into a validated evidence item."""
    if not isinstance(raw, dict):
        return None
    detail = str(raw.get("detail") or "").strip()
    if not detail:
        return None
    confidence = str(raw.get("confidence") or "medium").lower()
    if confidence not in CONFIDENCE_WEIGHTS:
        confidence = "medium"
    return {
        "source": str(raw.get("source") or "unknown"),
        "reference": str(raw.get("reference") or ""),
        "detail": detail[:800],
        "confidence": confidence,  # type: ignore[typeddict-item]
    }


def merge_evidence(*collections: list[EvidenceItem] | list[dict[str, Any]] | None) -> list[EvidenceItem]:
    """Merge evidence lists, deduplicating by source+reference+detail prefix."""
    merged: list[EvidenceItem] = []
    seen: set[str] = set()
    for collection in collections:
        for raw in collection or []:
            item = normalize_evidence(raw)
            if item is None:
                continue
            key = f"{item['source']}|{item['reference']}|{item['detail'][:120]}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def evidence_weight(item: EvidenceItem) -> float:
    return CONFIDENCE_WEIGHTS.get(item.get("confidence", "medium"), 0.6)


def evidence_from_tool_output(output: dict[str, Any]) -> list[EvidenceItem]:
    """Extract structured evidence from a diagnostic tool output dict."""
    items: list[EvidenceItem] = []
    structured = output.get("evidence")
    if isinstance(structured, list):
        for row in structured:
            item = normalize_evidence(row)
            if item:
                items.append(item)

    tool = str(output.get("tool") or "")
    if tool == "reconcile_crypto_com_open_orders":
        counts = output.get("counts") or {}
        if counts:
            items.append(
                {
                    "source": "exchange",
                    "reference": "reconciliation_counts",
                    "detail": (
                        f"Exchange={counts.get('exchange_live', 0)}, "
                        f"DB={counts.get('database_open', 0)}, "
                        f"dashboard={counts.get('dashboard_cache', 0)}"
                    ),
                    "confidence": "high",
                }
            )
        sources = output.get("sources") or {}
        exchange_meta = sources.get("exchange") or {}
        if exchange_meta.get("trigger_orders_error_code"):
            items.append(
                {
                    "source": "exchange",
                    "reference": "trigger_orders_api",
                    "detail": (
                        f"Trigger-order API error_code={exchange_meta.get('trigger_orders_error_code')}: "
                        f"{exchange_meta.get('trigger_orders_error')}"
                    ),
                    "confidence": "high",
                }
            )
        cred_diag = exchange_meta.get("credential_diagnostics") or {}
        present_pairs = [
            k.replace("_PRESENT", "")
            for k, v in cred_diag.items()
            if k.endswith("_PRESENT") and v
        ]
        if len(present_pairs) > 2:
            items.append(
                {
                    "source": "authentication",
                    "reference": "credential_pairs",
                    "detail": f"Multiple credential env vars present: {present_pairs}",
                    "confidence": "high",
                }
            )

    if tool == "inspect_health":
        status = output.get("status")
        if status:
            items.append(
                {
                    "source": "runtime",
                    "reference": "health_endpoint",
                    "detail": f"Health check status={status}",
                    "confidence": "high" if status == "healthy" else "medium",
                }
            )

    if output.get("root_cause"):
        items.append(
            {
                "source": "diagnostic",
                "reference": tool or "tool",
                "detail": str(output["root_cause"]),
                "confidence": "high",
            }
        )

    return items
