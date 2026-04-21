"""
Approval-gated Google Ads mutations (pause / budget / resume).

Uses the same OAuth + developer token wiring as ``run_google_ads_readonly_diagnostic``.
"""

from __future__ import annotations

import os
from typing import Any

from google.protobuf import field_mask_pb2

from app.jarvis.autonomous_agents import _load_google_ads_oauth_client_config, _normalize_ads_customer_id


def _failure(*, ok: bool, message: str) -> dict[str, Any]:
    return {"ok": ok, "error_message": str(message)[:1200]}


def _google_ads_client_from_params(params: dict[str, Any]) -> tuple[Any, str] | tuple[None, None]:
    """Returns (client, customer_id) or (None, None) on failure (caller should return _failure)."""
    creds_path = str(
        params.get("credentials_json")
        or os.getenv("JARVIS_GOOGLE_ADS_CREDENTIALS_JSON")
        or ""
    ).strip()
    developer_token = str(
        params.get("developer_token")
        or os.getenv("JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN")
        or ""
    ).strip()
    customer_id_raw = str(
        params.get("customer_id")
        or os.getenv("JARVIS_GOOGLE_ADS_CUSTOMER_ID")
        or ""
    ).strip()
    refresh_token = str(
        params.get("refresh_token")
        or os.getenv("JARVIS_GOOGLE_ADS_REFRESH_TOKEN")
        or ""
    ).strip()
    login_customer_id_raw = str(
        params.get("login_customer_id")
        or os.getenv("JARVIS_GOOGLE_ADS_LOGIN_CUSTOMER_ID")
        or ""
    ).strip()
    login_customer_id = _normalize_ads_customer_id(login_customer_id_raw)
    customer_id = _normalize_ads_customer_id(customer_id_raw)

    if not developer_token:
        return None, None
    if not customer_id:
        return None, None
    if not creds_path or not os.path.isfile(creds_path):
        return None, None
    if not refresh_token:
        return None, None

    oauth_client, _oauth_err = _load_google_ads_oauth_client_config(creds_path)
    if oauth_client is None:
        return None, None

    try:
        from google.ads.googleads.client import GoogleAdsClient  # type: ignore
    except Exception:
        return None, None

    try:
        client_cfg: dict[str, Any] = {
            "developer_token": developer_token,
            "client_id": str(oauth_client.get("client_id") or ""),
            "client_secret": str(oauth_client.get("client_secret") or ""),
            "refresh_token": refresh_token,
            "use_proto_plus": True,
        }
        if login_customer_id:
            client_cfg["login_customer_id"] = login_customer_id
        client = GoogleAdsClient.load_from_dict(client_cfg)
        return client, customer_id
    except Exception:
        return None, None


def _campaign_resource_name(customer_id: str, campaign_id: str) -> str:
    cid = "".join(ch for ch in campaign_id if ch.isdigit())
    return f"customers/{customer_id}/campaigns/{cid}"


def run_google_ads_pause_campaign(params: dict[str, Any]) -> dict[str, Any]:
    client, customer_id = _google_ads_client_from_params(params)
    if client is None or not customer_id:
        return _failure(ok=False, message="Google Ads no está configurado para mutaciones (credenciales / entorno).")
    cid = str(params.get("campaign_id") or "").strip()
    if not cid:
        return _failure(ok=False, message="Falta campaign_id en los parámetros.")
    try:
        campaign_service = client.get_service("CampaignService")
        campaign_operation = client.get_type("CampaignOperation")
        campaign = client.get_type("Campaign")
        campaign.resource_name = _campaign_resource_name(customer_id, cid)
        campaign.status = client.enums.CampaignStatusEnum.CampaignStatus.PAUSED
        campaign_operation.update = campaign
        mask = field_mask_pb2.FieldMask(paths=["status"])
        campaign_operation.update_mask.CopyFrom(mask)
        campaign_service.mutate_campaigns(customer_id=customer_id, operations=[campaign_operation])
        return {"ok": True, "campaign_id": cid}
    except Exception as exc:
        return _failure(ok=False, message=str(exc))


def run_google_ads_reduce_campaign_budget(params: dict[str, Any]) -> dict[str, Any]:
    client, customer_id = _google_ads_client_from_params(params)
    if client is None or not customer_id:
        return _failure(ok=False, message="Google Ads no está configurado para mutaciones (credenciales / entorno).")
    budget_rn = str(params.get("campaign_budget_resource_name") or "").strip()
    proposed = params.get("proposed_budget_amount")
    new_micros: int | None = None
    if proposed is not None and str(proposed).strip():
        try:
            amt = float(str(proposed).replace(",", "."))
            new_micros = int(round(amt * 1_000_000))
        except (TypeError, ValueError):
            new_micros = None
    if not budget_rn or new_micros is None or new_micros <= 0:
        return _failure(
            ok=False,
            message="Faltan campaign_budget_resource_name o proposed_budget_amount válido para el ajuste.",
        )
    try:
        cb_service = client.get_service("CampaignBudgetService")
        op = client.get_type("CampaignBudgetOperation")
        budget = client.get_type("CampaignBudget")
        budget.resource_name = budget_rn
        budget.amount_micros = new_micros
        op.update = budget
        mask = field_mask_pb2.FieldMask(paths=["amount_micros"])
        op.update_mask.CopyFrom(mask)
        cb_service.mutate_campaign_budgets(customer_id=customer_id, operations=[op])
        return {"ok": True, "new_budget_micros": new_micros}
    except Exception as exc:
        return _failure(ok=False, message=str(exc))


def run_google_ads_resume_campaign(params: dict[str, Any]) -> dict[str, Any]:
    client, customer_id = _google_ads_client_from_params(params)
    if client is None or not customer_id:
        return _failure(ok=False, message="Google Ads no está configurado para mutaciones (credenciales / entorno).")
    cid = str(params.get("campaign_id") or "").strip()
    if not cid:
        return _failure(ok=False, message="Falta campaign_id en los parámetros.")
    try:
        ga_service = client.get_service("GoogleAdsService")
        req = client.get_type("SearchGoogleAdsRequest")
        req.customer_id = customer_id
        req.query = (
            f"SELECT campaign.id, campaign.status FROM campaign WHERE campaign.id = {int(cid)} LIMIT 1"
        )
        current_status = ""
        for row in ga_service.search(request=req):
            camp = getattr(row, "campaign", None)
            if camp is None:
                continue
            st = getattr(camp, "status", None)
            if st is not None:
                current_status = str(getattr(st, "name", None) or st or "").strip()
            break
        if current_status == "ENABLED":
            return {"ok": True, "no_op": True, "campaign_id": cid}

        campaign_service = client.get_service("CampaignService")
        campaign_operation = client.get_type("CampaignOperation")
        campaign = client.get_type("Campaign")
        campaign.resource_name = _campaign_resource_name(customer_id, cid)
        campaign.status = client.enums.CampaignStatusEnum.CampaignStatus.ENABLED
        campaign_operation.update = campaign
        mask = field_mask_pb2.FieldMask(paths=["status"])
        campaign_operation.update_mask.CopyFrom(mask)
        campaign_service.mutate_campaigns(customer_id=customer_id, operations=[campaign_operation])
        return {"ok": True, "no_op": False, "campaign_id": cid}
    except Exception as exc:
        msg = str(exc)
        return _failure(ok=False, message=msg)
