"""
Seeded catalog of documented secrets (metadata only — no real values).

Logical names use dot notation; they map to AWS Parameter Store paths via
``aws_sync.parameter_name(environment, name)``.
"""

from __future__ import annotations

from typing import Any, TypedDict
from urllib.parse import urlencode

import mappings
import storage


class InventoryEntry(TypedDict):
    name: str
    environment: str
    category: str
    description: str
    expected_target: str


# Documented in-repo references: docs/runbooks/secrets_runtime_env.md, PROD_STATUS_UPDATE,
# TELEGRAM_*, NOTION_*, exchange keys, etc. Values are never stored here.
INVENTORY: list[InventoryEntry] = [
    {
        "name": "telegram.atp_control.bot_token",
        "environment": "prod",
        "category": "telegram",
        "description": "ATP control bot token (polling /task intake on prod backend).",
        "expected_target": "ATP prod backend-aws (TELEGRAM_ATP_CONTROL_BOT_TOKEN / runtime.env)",
    },
    {
        "name": "telegram.main.bot_token",
        "environment": "prod",
        "category": "telegram",
        "description": "Primary Telegram bot token for alerts / notifier (TELEGRAM_BOT_TOKEN).",
        "expected_target": "ATP prod backend-aws, secrets/runtime.env",
    },
    {
        "name": "telegram.chat_id",
        "environment": "prod",
        "category": "telegram",
        "description": "Telegram chat/channel ID for ATP alerts (TELEGRAM_CHAT_ID or *_AWS).",
        "expected_target": "ATP prod backend-aws env",
    },
    {
        "name": "notion.api_key",
        "environment": "prod",
        "category": "notion",
        "description": "Notion integration token (NOTION_API_KEY).",
        "expected_target": "ATP prod backend-aws, SSM or runtime.env",
    },
    {
        "name": "notion.api_key",
        "environment": "lab",
        "category": "notion",
        "description": "Notion integration token for LAB (NOTION_API_KEY).",
        "expected_target": "ATP lab backend, SSM /automated-trading-platform/lab/notion/api_key",
    },
    {
        "name": "notion.task_database_id",
        "environment": "prod",
        "category": "notion",
        "description": "Notion database ID for task intake (NOTION_TASK_DB).",
        "expected_target": "ATP prod backend-aws env",
    },
    {
        "name": "notion.task_database_id",
        "environment": "lab",
        "category": "notion",
        "description": "Notion task database ID for LAB (NOTION_TASK_DB).",
        "expected_target": "ATP lab backend env",
    },
    {
        "name": "api.atp_key",
        "environment": "prod",
        "category": "backend",
        "description": "x-api-key for internal ATP API (ATP_API_KEY / INTERNAL_API_KEY).",
        "expected_target": "secrets/runtime.env on prod host",
    },
    {
        "name": "api.atp_key",
        "environment": "lab",
        "category": "backend",
        "description": "x-api-key for internal ATP API on LAB.",
        "expected_target": "LAB runtime.env / .env",
    },
    {
        "name": "diagnostics.api_key",
        "environment": "prod",
        "category": "backend",
        "description": "Diagnostics / health tooling API key (DIAGNOSTICS_API_KEY).",
        "expected_target": "ATP prod env",
    },
    {
        "name": "exchange.custom.api_key",
        "environment": "prod",
        "category": "exchange",
        "description": "Custom exchange API key (EXCHANGE_CUSTOM_API_KEY).",
        "expected_target": "ATP prod trading backend",
    },
    {
        "name": "exchange.custom.api_secret",
        "environment": "prod",
        "category": "exchange",
        "description": "Custom exchange API secret (EXCHANGE_CUSTOM_API_SECRET).",
        "expected_target": "ATP prod trading backend",
    },
    {
        "name": "openclaw.ghcr_token",
        "environment": "lab",
        "category": "openclaw",
        "description": "GHCR pull token for OpenClaw images (SSM /openclaw/ghcr-token pattern).",
        "expected_target": "LAB host docker login / SSM",
    },
]


def inventory_key(name: str, environment: str) -> tuple[str, str]:
    return (name.strip().lower(), environment.strip().lower())


def _masked_preview(value: str, keep: int = 10) -> str:
    v = value or ""
    if not v.strip():
        return "Missing"
    if len(v) <= keep:
        return v
    return f"{v[:keep]}..."


def index_records_by_inventory_key(
    records: list[storage.SecretRecord],
) -> dict[tuple[str, str], storage.SecretRecord]:
    out: dict[tuple[str, str], storage.SecretRecord] = {}
    for r in records:
        k = inventory_key(r.name, r.environment)
        out[k] = r
    return out


def build_display_rows(records: list[storage.SecretRecord]) -> list[dict[str, Any]]:
    """
    Merge seeded inventory with vault records. Catalog rows first; then vault-only rows.
    """
    by_key = index_records_by_inventory_key(records)
    inv_keys = {inventory_key(i["name"], i["environment"]) for i in INVENTORY}
    seen_ids: set[str] = set()
    rows: list[dict[str, Any]] = []

    for inv in INVENTORY:
        k = inventory_key(inv["name"], inv["environment"])
        rec = by_key.get(k)
        if rec:
            seen_ids.add(rec.id)
        plain = rec.value_plain if rec else ""
        has_value = bool(plain.strip())
        masked = _masked_preview(plain)
        add_q = urlencode(
            {
                "pf_name": inv["name"],
                "pf_env": inv["environment"],
                "pf_cat": inv["category"],
            }
        )
        is_seeded = True
        in_vault = rec is not None
        is_missing = not has_value
        apply_ready = bool(rec and has_value and mappings.get_deploy_target(inv["name"], inv["environment"]))
        verify_ready = bool(rec and has_value)
        badges = []
        if in_vault:
            badges.append("In vault")
        if is_missing:
            badges.append("Missing")
        badges.append("Seeded" if is_seeded else "Custom")
        if apply_ready:
            badges.append("Apply ready")
        if verify_ready:
            badges.append("Verify ready")
        rows.append(
            {
                "name": inv["name"],
                "environment": inv["environment"],
                "category": (rec.category if rec and rec.category else inv["category"]),
                "description": (rec.description if rec and rec.description else inv["description"]),
                "expected_target": inv["expected_target"],
                "notes": rec.notes if rec else "",
                "id": rec.id if rec else None,
                "last_updated": rec.last_updated if rec else "",
                "has_value": has_value,
                "value_masked": masked,
                "in_vault": in_vault,
                "seeded": is_seeded,
                "missing": is_missing,
                "apply_ready": apply_ready,
                "verify_ready": verify_ready,
                "badges": badges,
                "add_href": None if rec else f"/?{add_q}#add-secret",
            }
        )

    for rec in records:
        if rec.id in seen_ids:
            continue
        k = inventory_key(rec.name, rec.environment)
        if k in inv_keys:
            continue
        plain = rec.value_plain
        has_value = bool(plain.strip())
        masked = _masked_preview(plain)
        is_seeded = False
        in_vault = True
        is_missing = not has_value
        apply_ready = bool(has_value and mappings.get_deploy_target(rec.name, rec.environment))
        verify_ready = bool(has_value)
        badges = []
        if in_vault:
            badges.append("In vault")
        if is_missing:
            badges.append("Missing")
        badges.append("Seeded" if is_seeded else "Custom")
        if apply_ready:
            badges.append("Apply ready")
        if verify_ready:
            badges.append("Verify ready")
        rows.append(
            {
                "name": rec.name,
                "environment": rec.environment,
                "category": rec.category or "other",
                "description": rec.description or "User-added (not in catalog).",
                "expected_target": "—",
                "notes": rec.notes,
                "id": rec.id,
                "last_updated": rec.last_updated,
                "has_value": has_value,
                "value_masked": masked,
                "in_vault": in_vault,
                "seeded": is_seeded,
                "missing": is_missing,
                "apply_ready": apply_ready,
                "verify_ready": verify_ready,
                "badges": badges,
                "add_href": None,
            }
        )

    return rows


def filter_rows(
    rows: list[dict[str, Any]],
    *,
    q: str = "",
    env: str = "",
    category: str = "",
    status: str = "",
) -> list[dict[str, Any]]:
    qn = (q or "").strip().lower()
    envn = (env or "").strip().lower()
    catn = (category or "").strip().lower()
    st = (status or "").strip().lower()

    def row_matches(r: dict[str, Any]) -> bool:
        if envn and r.get("environment", "").lower() != envn:
            return False
        if catn and r.get("category", "").lower() != catn:
            return False
        if qn:
            hay = " ".join(
                [
                    str(r.get("name", "")),
                    str(r.get("description", "")),
                    str(r.get("expected_target", "")),
                    str(r.get("notes", "")),
                    str(r.get("category", "")),
                ]
            ).lower()
            if qn not in hay:
                return False
        if st:
            flags = {
                "in-vault": bool(r.get("in_vault")),
                "missing": bool(r.get("missing")),
                "seeded": bool(r.get("seeded")),
                "custom": not bool(r.get("seeded")),
                "apply-ready": bool(r.get("apply_ready")),
                "verify-ready": bool(r.get("verify_ready")),
            }
            if not flags.get(st, False):
                return False
        return True

    return [r for r in rows if row_matches(r)]
