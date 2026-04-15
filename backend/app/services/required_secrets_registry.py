"""
Registered secrets for dashboard status, automation readiness, and safe runtime.env intake.

Rules are exercised by ``backend/tests/test_required_secrets_registry.py``.
"""

from __future__ import annotations

import os
from typing import Any, Final

from app.core.environment import getRuntimeEnv, is_atp_trading_only, is_aws

MARKETING_SETTINGS_ENV_VARS: Final[frozenset[str]] = frozenset()


def _legacy_pat_active() -> bool:
    return (os.getenv("ALLOW_LEGACY_GITHUB_PAT") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ) and bool((os.getenv("GITHUB_TOKEN") or "").strip())


def _notion_db() -> str:
    return (os.getenv("NOTION_TASK_DB") or os.getenv("NOTION_TASKS_DB") or "").strip()


def _notion_ok() -> bool:
    return bool((os.getenv("NOTION_API_KEY") or "").strip() and _notion_db())


def _openclaw_ok() -> bool:
    return bool((os.getenv("OPENCLAW_API_TOKEN") or "").strip() and (os.getenv("OPENCLAW_API_URL") or "").strip())


def _github_app_ok() -> bool:
    return all(
        bool((os.getenv(k) or "").strip())
        for k in ("GITHUB_APP_ID", "GITHUB_APP_INSTALLATION_ID", "GITHUB_APP_PRIVATE_KEY_B64")
    )


def _github_app_client_id_status() -> str | None:
    if not is_aws():
        return None
    if _legacy_pat_active():
        return "not_applicable"
    if not (os.getenv("GITHUB_APP_ID") or "").strip():
        return None
    if (os.getenv("GITHUB_APP_CLIENT_ID") or "").strip():
        return "present"
    return "missing"


def _item(
    env_var: str,
    blocked_service: str,
    why: str,
    ssm_parameter_name: str | None = None,
) -> dict[str, Any]:
    return {
        "id": env_var.lower().replace("_", "-"),
        "env_var": env_var,
        "blocked_service": blocked_service,
        "why": why,
        "ssm_parameter_name": ssm_parameter_name,
    }


def _automation_readiness_missing() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not (os.getenv("NOTION_API_KEY") or "").strip():
        out.append(
            _item(
                "NOTION_API_KEY",
                "notion_automation",
                "Required before disabling ATP_TRADING_ONLY (Notion task intake).",
            )
        )
    if not _notion_db():
        out.append(
            _item(
                "NOTION_TASK_DB",
                "notion_automation",
                "Required before disabling ATP_TRADING_ONLY (Notion database id).",
            )
        )
    if not (os.getenv("OPENCLAW_API_TOKEN") or "").strip():
        out.append(
            _item(
                "OPENCLAW_API_TOKEN",
                "openclaw",
                "Required before disabling ATP_TRADING_ONLY (OpenClaw API token).",
            )
        )
    if not (os.getenv("OPENCLAW_API_URL") or "").strip():
        out.append(
            _item(
                "OPENCLAW_API_URL",
                "openclaw",
                "Required before disabling ATP_TRADING_ONLY (OpenClaw base URL).",
            )
        )
    if is_aws() and not _legacy_pat_active():
        if not (os.getenv("GITHUB_APP_ID") or "").strip():
            out.append(
                _item(
                    "GITHUB_APP_ID",
                    "github_app",
                    "Required on AWS for deploy when not using legacy PAT.",
                )
            )
        if not (os.getenv("GITHUB_APP_INSTALLATION_ID") or "").strip():
            out.append(
                _item(
                    "GITHUB_APP_INSTALLATION_ID",
                    "github_app",
                    "Required on AWS for deploy when not using legacy PAT.",
                )
            )
        if not (os.getenv("GITHUB_APP_PRIVATE_KEY_B64") or "").strip():
            out.append(
                _item(
                    "GITHUB_APP_PRIVATE_KEY_B64",
                    "github_app",
                    "Required on AWS for deploy when not using legacy PAT.",
                )
            )
    return out


def _primary_missing() -> list[dict[str, Any]]:
    """Blocking missing secrets for the active (non–trading-only) stack."""
    if is_atp_trading_only():
        return []

    out: list[dict[str, Any]] = []
    if not (os.getenv("NOTION_API_KEY") or "").strip():
        out.append(_item("NOTION_API_KEY", "notion_automation", "Notion API key is not set."))
    if not _notion_db():
        out.append(_item("NOTION_TASK_DB", "notion_automation", "Notion task database id is not set."))
    if not _openclaw_ok():
        if not (os.getenv("OPENCLAW_API_TOKEN") or "").strip():
            out.append(_item("OPENCLAW_API_TOKEN", "openclaw", "OpenClaw token is not set."))
        if not (os.getenv("OPENCLAW_API_URL") or "").strip():
            out.append(_item("OPENCLAW_API_URL", "openclaw", "OpenClaw URL is not set."))

    if is_aws() and not _legacy_pat_active() and not _github_app_ok():
        if not (os.getenv("GITHUB_APP_ID") or "").strip():
            out.append(_item("GITHUB_APP_ID", "github_app", "GitHub App id is not set."))
        if not (os.getenv("GITHUB_APP_INSTALLATION_ID") or "").strip():
            out.append(_item("GITHUB_APP_INSTALLATION_ID", "github_app", "GitHub App installation id is not set."))
        if not (os.getenv("GITHUB_APP_PRIVATE_KEY_B64") or "").strip():
            out.append(
                _item("GITHUB_APP_PRIVATE_KEY_B64", "github_app", "GitHub App private key (base64) is not set.")
            )
    elif is_aws() and _legacy_pat_active() and not (os.getenv("GITHUB_TOKEN") or "").strip():
        out.append(_item("GITHUB_TOKEN", "github_legacy", "Legacy PAT path enabled but GITHUB_TOKEN is empty."))

    return out


def _effective_env_value(env_var: str) -> str:
    if env_var == "NOTION_TASK_DB":
        return _notion_db()
    return (os.getenv(env_var) or "").strip()


def _mask_last3(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return "(empty)"
    if len(s) <= 3:
        return "•••" + s
    return "•••••••" + s[-3:]


# Dashboard catalog: human label, optional group for UI ordering.
_CATALOG_META: list[tuple[str, str, str]] = [
    ("EXCHANGE_CUSTOM_API_KEY", "Crypto.com API key", "trading"),
    ("EXCHANGE_CUSTOM_API_SECRET", "Crypto.com API secret", "trading"),
    ("EXCHANGE_CUSTOM_BASE_URL", "Crypto.com REST base URL", "trading"),
    ("ATP_API_KEY", "Engine / internal x-api-key (ATP_API_KEY)", "api"),
    ("INTERNAL_API_KEY", "Internal API key (fallback for x-api-key)", "api"),
    ("DIAGNOSTICS_API_KEY", "Diagnostics API key", "api"),
    ("TELEGRAM_BOT_TOKEN_AWS", "Telegram bot token (AWS plain)", "telegram"),
    ("TELEGRAM_CHAT_ID_AWS", "Telegram chat id (AWS)", "telegram"),
    ("NOTION_API_KEY", "Notion API key", "automation"),
    ("NOTION_TASK_DB", "Notion task database id", "automation"),
    ("OPENCLAW_API_TOKEN", "OpenClaw API token", "automation"),
    ("OPENCLAW_API_URL", "OpenClaw API URL", "automation"),
    ("GITHUB_APP_ID", "GitHub App ID", "github"),
    ("GITHUB_APP_CLIENT_ID", "GitHub App Client ID", "github"),
    ("GITHUB_APP_INSTALLATION_ID", "GitHub App installation id", "github"),
    ("GITHUB_APP_PRIVATE_KEY_B64", "GitHub App private key (base64)", "github"),
    ("GITHUB_TOKEN", "GitHub token (legacy PAT)", "github"),
    ("ALLOW_LEGACY_GITHUB_PAT", "Allow legacy GitHub PAT (true/false)", "github"),
]

# Allowlisted POST /admin/secrets-intake keys (runtime.env + process env). Never arbitrary env names.
INTAKE_ALLOWLIST: Final[frozenset[str]] = frozenset({name for name, _, _ in _CATALOG_META})


def is_allowed_intake_key(name: str) -> bool:
    return (name or "").strip() in INTAKE_ALLOWLIST


def _catalog_row(env_var: str, label: str, group: str) -> dict[str, Any]:
    raw = _effective_env_value(env_var)
    present = bool(raw)
    return {
        "env_var": env_var,
        "label": label,
        "group": group,
        "present": present,
        "masked": _mask_last3(raw),
        "intake_allowed": is_allowed_intake_key(env_var),
    }


def build_secrets_catalog() -> list[dict[str, Any]]:
    return [_catalog_row(ev, lab, grp) for ev, lab, grp in _CATALOG_META]


def compute_missing_settings() -> list[dict[str, Any]]:
    """Marketing-style settings gaps (optional); kept for atp_system_review imports."""
    return []


def evaluate_requirements() -> dict[str, Any]:
    missing = _primary_missing()
    overall: str = "ok" if not missing else "action_required"

    if is_atp_trading_only():
        ar_missing = _automation_readiness_missing()
        ar_overall = "ok" if not ar_missing else "action_required"
        automation_readiness: dict[str, Any] = {
            "applicable": True,
            "overall": ar_overall,
            "missing": ar_missing,
            "note": "These are needed before you can turn off trading-only mode (ATP_TRADING_ONLY=0).",
        }
    else:
        automation_readiness = {
            "applicable": False,
            "missing": [],
            "note": None,
        }

    ctx = {
        "atp_trading_only": bool(is_atp_trading_only()),
        "environment": getRuntimeEnv(),
        "aws": bool(is_aws()),
        "github_legacy_pat_active": _legacy_pat_active(),
        "github_app_client_id_status": _github_app_client_id_status(),
    }

    return {
        "overall": overall,
        "missing": missing,
        "skipped_count": 0,
        "context": ctx,
        "automation_readiness": automation_readiness,
        "secrets_catalog": build_secrets_catalog(),
    }
