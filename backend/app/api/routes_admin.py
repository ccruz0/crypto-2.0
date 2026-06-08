"""
Admin-only API endpoints
Requires X-Admin-Key header matching ADMIN_ACTIONS_KEY env var
"""
import json
import os
import logging
import time
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Header, HTTPException, Depends, Body, UploadFile, File
from typing import Optional, Any
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.telegram_notifier import telegram_notifier
from app.services.system_health import record_telegram_send_result
from app.services.signal_monitor import signal_monitor_service
from app.models.watchlist_master import WatchlistItem
from app.jarvis.secure_runtime_env_write import persist_env_var_value, runtime_env_path

router = APIRouter()


class EvaluateSymbolBody(BaseModel):
    symbol: str = "BTC_USDT"


class RotateAdminKeyBody(BaseModel):
    new_admin_key: str


class SecretIntakeBody(BaseModel):
    env_var: str
    value: str
    persist_ssm: bool = False


class GoogleIntegrationsSettingsUpdateBody(BaseModel):
    ga4_property_id: Optional[str] = None
    gsc_site_url: Optional[str] = None
    google_ads_developer_token: Optional[str] = None
    google_ads_customer_id: Optional[str] = None


logger = logging.getLogger(__name__)

_MIN_ADMIN_KEY_LEN = 16

# Rate limiting: last test timestamp (in-memory, per-process)
_last_test_telegram_ts: Optional[float] = None
_TEST_TELEGRAM_COOLDOWN_SECONDS = 60


_TELEGRAM_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")
_PROD_INSTANCE_ID = "i-087953603011543c5"
_PROD_REGION = "ap-southeast-1"
_PROD_TELEGRAM_TOKEN_PARAM = "/automated-trading-platform/prod/telegram/bot_token"
_GA4_ENV_KEY = "JARVIS_GA4_CREDENTIALS_JSON"
_GA4_PROPERTY_ENV_KEY = "JARVIS_GA4_PROPERTY_ID"
_GSC_ENV_KEY = "JARVIS_GSC_CREDENTIALS_JSON"
_GSC_SITE_URL_ENV_KEY = "JARVIS_GSC_SITE_URL"
_GOOGLE_ADS_ENV_KEY = "JARVIS_GOOGLE_ADS_CREDENTIALS_JSON"
_GOOGLE_ADS_DEVELOPER_TOKEN_ENV_KEY = "JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN"
_GOOGLE_ADS_CUSTOMER_ID_ENV_KEY = "JARVIS_GOOGLE_ADS_CUSTOMER_ID"
_GOOGLE_CREDENTIALS_DIR = Path(runtime_env_path()).resolve().parent / "credentials"
_GA4_CREDENTIALS_PATH = _GOOGLE_CREDENTIALS_DIR / "ga.json"
_GSC_CREDENTIALS_PATH = _GOOGLE_CREDENTIALS_DIR / "gsc.json"
_GOOGLE_ADS_CREDENTIALS_PATH = _GOOGLE_CREDENTIALS_DIR / "google_ads.json"
_GA4_UPLOAD_MAX_BYTES = 2 * 1024 * 1024  # 2MB


class TelegramTokenUpdateBody(BaseModel):
    token: str


def _mask_token_suffix(token: str) -> str:
    token = (token or "").strip()
    if not token:
        return "***"
    return f"***{token[-8:]}"


def _validate_telegram_token_shape(token: str) -> bool:
    return bool(_TELEGRAM_TOKEN_RE.match((token or "").strip()))


def _run_prod_runtime_refresh_via_ssm(ssm_client) -> tuple[bool, str]:
    """Update PROD runtime.env from SSM and restart backend-aws (no token in command body)."""
    script = r"""
set -euo pipefail
cd /home/ubuntu/automated-trading-platform
python3 - <<'PY'
import os
import re
import boto3

PARAM_NAME = "/automated-trading-platform/prod/telegram/bot_token"
RUNTIME_ENV = "/home/ubuntu/automated-trading-platform/secrets/runtime.env"
REGION = "ap-southeast-1"

ssm = boto3.client("ssm", region_name=REGION)
token = ssm.get_parameter(Name=PARAM_NAME, WithDecryption=True)["Parameter"]["Value"].strip()
if not token:
    raise SystemExit("empty token from ssm")

lines = []
if os.path.isfile(RUNTIME_ENV):
    with open(RUNTIME_ENV, "r", encoding="utf-8") as f:
        lines = f.readlines()

updated = []
found = False
found_bot = False
found_atp_control = False
for line in lines:
    if line.startswith("TELEGRAM_BOT_TOKEN="):
        updated.append("TELEGRAM_BOT_TOKEN=" + token + "\n")
        found_bot = True
    elif line.startswith("TELEGRAM_ATP_CONTROL_BOT_TOKEN="):
        updated.append("TELEGRAM_ATP_CONTROL_BOT_TOKEN=" + token + "\n")
        found_atp_control = True
    else:
        updated.append(line)

if not found_bot:
    if updated and not updated[-1].endswith("\n"):
        updated.append("\n")
    updated.append("TELEGRAM_BOT_TOKEN=" + token + "\n")
if not found_atp_control:
    updated.append("TELEGRAM_ATP_CONTROL_BOT_TOKEN=" + token + "\n")

with open(RUNTIME_ENV, "w", encoding="utf-8") as f:
    f.writelines(updated)
PY
docker compose --profile aws restart backend-aws
"""
    resp = ssm_client.send_command(
        InstanceIds=[_PROD_INSTANCE_ID],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [script]},
        TimeoutSeconds=180,
    )
    command_id = resp.get("Command", {}).get("CommandId")
    if not command_id:
        return False, "no CommandId from SSM send-command"

    for _ in range(120):
        time.sleep(1)
        try:
            inv = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=_PROD_INSTANCE_ID,
            )
        except Exception:
            continue
        status = (inv.get("Status") or "").strip()
        if status in ("Success", "Failed", "Cancelled", "TimedOut"):
            if status == "Success":
                return True, ""
            err = (inv.get("StandardErrorContent") or inv.get("StandardOutputContent") or "").strip()
            return False, (err[:300] or f"ssm status={status}")

    return False, "runtime refresh timed out"


def verify_admin_key(x_admin_key: Optional[str] = Header(None)) -> str:
    """Verify admin key from header"""
    expected_key = os.getenv("ADMIN_ACTIONS_KEY")
    
    if not expected_key:
        logger.warning("ADMIN_ACTIONS_KEY not set - admin endpoints disabled")
        raise HTTPException(status_code=401, detail="Admin actions not configured")
    
    if not x_admin_key or x_admin_key != expected_key:
        logger.warning(f"Invalid admin key attempt (header present: {x_admin_key is not None})")
        raise HTTPException(status_code=401, detail="unauthorized")
    
    return x_admin_key


def _ga4_status_payload(
    *,
    success: bool,
    uploaded: bool,
    valid: bool,
    path: Optional[str],
    error: Optional[str],
) -> dict[str, Any]:
    return {
        "success": success,
        "uploaded": uploaded,
        "valid": valid,
        "path": path,
        "error": error,
        "env_key": _GA4_ENV_KEY,
    }


async def _validate_uploaded_json_file(
    uploaded_file: UploadFile,
    *,
    max_bytes: int = _GA4_UPLOAD_MAX_BYTES,
) -> bytes:
    filename = (uploaded_file.filename or "").strip()
    if not filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Only .json files are allowed")

    try:
        raw = await uploaded_file.read(max_bytes + 1)
    except Exception as exc:
        logger.warning("google_credentials_upload_read_failed err=%s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="Failed to read uploaded file") from exc

    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail="File too large (max 2MB)")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Credentials file must be a JSON object")
    return raw


def _write_credentials_file_atomically(target_path: Path, raw: bytes) -> None:
    _GOOGLE_CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f"{target_path.stem}-credentials-",
            suffix=".json",
            dir=str(target_path.parent),
            delete=False,
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            tmp_file.write(raw)
            tmp_file.flush()
            os.fchmod(tmp_file.fileno(), 0o600)
        os.replace(tmp_path, target_path)
        os.chmod(target_path, 0o600)
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _build_credentials_status_payload(
    *,
    env_key: str,
    success: bool,
    uploaded: bool,
    valid: bool,
    filename: Optional[str],
    error: Optional[str],
) -> dict[str, Any]:
    return {
        "success": success,
        "uploaded": uploaded,
        "valid": valid,
        "filename": filename,
        "error": error,
        "env_key": env_key,
    }


def _resolve_credentials_status(
    *,
    env_key: str,
    default_path: Path,
    validator: "callable[[Path], tuple[bool, Optional[str]]]",
    status_log_event: str,
) -> dict[str, Any]:
    env_value = (os.getenv(env_key) or "").strip()
    configured_path = Path(env_value) if env_value else default_path
    file_exists = configured_path.is_file()
    filename = configured_path.name if (env_value or file_exists) else None

    if not env_value and not file_exists:
        status = _build_credentials_status_payload(
            env_key=env_key,
            success=False,
            uploaded=False,
            valid=False,
            filename=None,
            error="Credentials JSON is missing",
        )
    elif not env_value:
        status = _build_credentials_status_payload(
            env_key=env_key,
            success=False,
            uploaded=True,
            valid=False,
            filename=filename,
            error=f"{env_key} is not set",
        )
    elif not file_exists:
        status = _build_credentials_status_payload(
            env_key=env_key,
            success=False,
            uploaded=False,
            valid=False,
            filename=filename,
            error="Credentials JSON is missing",
        )
    else:
        valid, validation_error = validator(configured_path)
        status = _build_credentials_status_payload(
            env_key=env_key,
            success=valid,
            uploaded=True,
            valid=valid,
            filename=filename,
            error=validation_error,
        )

    logger.info(
        "%s success=%s uploaded=%s valid=%s filename=%s error=%s",
        status_log_event,
        status["success"],
        status["uploaded"],
        status["valid"],
        status["filename"] or "",
        status["error"] or "",
    )
    return status


def _validate_ga4_credentials_json(path: Path) -> tuple[bool, Optional[str]]:
    """Validate credentials with GA4 client init + lightweight query."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        if not isinstance(parsed, dict):
            return False, "GA4 credentials JSON is malformed"
    except Exception:
        return False, "GA4 credentials JSON is malformed"

    try:
        from google.oauth2 import service_account
        from google.analytics.data_v1beta import BetaAnalyticsDataClient

        scopes = ["https://www.googleapis.com/auth/analytics.readonly"]
        credentials = service_account.Credentials.from_service_account_file(
            str(path),
            scopes=scopes,
        )
        client = BetaAnalyticsDataClient(credentials=credentials)
    except Exception as exc:
        return False, f"GA4 client initialization failed: {exc}"

    property_id_raw = (os.getenv(_GA4_PROPERTY_ENV_KEY) or "").strip()
    if not property_id_raw:
        return False, "GA4 property ID is missing"
    property_id = property_id_raw.replace("properties/", "").strip()
    if not property_id:
        return False, "GA4 property ID is missing"

    try:
        client.run_report(
            request={
                "property": f"properties/{property_id}",
                "date_ranges": [{"start_date": "1daysAgo", "end_date": "today"}],
                "metrics": [{"name": "activeUsers"}],
                "limit": 1,
            }
        )
        logger.info(
            "ga4_credentials_validation_query_success path=%s property_id=%s",
            str(path),
            property_id,
        )
        try:
            transport = getattr(client, "transport", None)
            close_fn = getattr(transport, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            # Transport close is best-effort only.
            pass
        return True, None
    except Exception as exc:
        logger.warning(
            "ga4_credentials_validation_query_failed path=%s property_id=%s error=%s",
            str(path),
            property_id,
            str(exc),
        )
        return False, f"GA4 credentials do not have access to property {property_id}: {exc}"


def _resolve_ga4_status() -> dict[str, Any]:
    return _resolve_credentials_status(
        env_key=_GA4_ENV_KEY,
        default_path=_GA4_CREDENTIALS_PATH,
        validator=_validate_ga4_credentials_json,
        status_log_event="ga4_credentials_status_checked",
    )


def _validate_gsc_credentials_json(path: Path) -> tuple[bool, Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        if not isinstance(parsed, dict):
            return False, "Search Console credentials JSON is malformed"
    except Exception:
        return False, "Search Console credentials JSON is malformed"

    try:
        from google.oauth2 import service_account
    except Exception as exc:
        return False, f"Search Console credentials initialization failed: {exc}"

    scopes = ["https://www.googleapis.com/auth/webmasters.readonly"]
    try:
        credentials = service_account.Credentials.from_service_account_file(
            str(path),
            scopes=scopes,
        )
    except Exception as exc:
        return False, f"Search Console credentials initialization failed: {exc}"

    site_url = (os.getenv(_GSC_SITE_URL_ENV_KEY) or "").strip()
    if not site_url:
        return False, "Search Console site URL is missing"

    try:
        from google.auth.transport.requests import AuthorizedSession  # type: ignore
    except Exception:
        return (
            False,
            "Search Console credentials are initialized, but live site access validation is not yet available in this build.",
        )

    try:
        session = AuthorizedSession(credentials)
        endpoint = (
            "https://searchconsole.googleapis.com/webmasters/v3/sites/"
            + quote(site_url, safe="")
        )
        response = session.get(endpoint, timeout=10)
        if response.status_code == 200:
            return True, None
        return (
            False,
            f"Search Console credentials do not have access to site {site_url}: HTTP {response.status_code}",
        )
    except Exception as exc:
        return False, f"Search Console credentials do not have access to site {site_url}: {exc}"


def _resolve_gsc_status() -> dict[str, Any]:
    return _resolve_credentials_status(
        env_key=_GSC_ENV_KEY,
        default_path=_GSC_CREDENTIALS_PATH,
        validator=_validate_gsc_credentials_json,
        status_log_event="gsc_credentials_status_checked",
    )


def _validate_google_ads_credentials_json(path: Path) -> tuple[bool, Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        if not isinstance(parsed, dict):
            return False, "Google Ads credentials JSON is malformed"
    except Exception:
        return False, "Google Ads credentials JSON is malformed"

    try:
        from google.oauth2 import service_account

        service_account.Credentials.from_service_account_file(
            str(path),
            scopes=["https://www.googleapis.com/auth/adwords"],
        )
    except Exception as exc:
        return False, f"Google Ads credentials initialization failed: {exc}"

    developer_token = (os.getenv(_GOOGLE_ADS_DEVELOPER_TOKEN_ENV_KEY) or "").strip()
    if not developer_token:
        return False, "Google Ads developer token is missing"

    customer_id = (os.getenv(_GOOGLE_ADS_CUSTOMER_ID_ENV_KEY) or "").strip()
    if not customer_id:
        return False, "Google Ads customer ID is missing"

    try:
        from google.ads.googleads.client import GoogleAdsClient  # type: ignore
    except Exception:
        return (
            False,
            "Google Ads credentials are initialized, but live Google Ads validation is unavailable in this build.",
        )

    normalized_customer_id = customer_id.replace("-", "").strip()
    if not normalized_customer_id:
        return False, "Google Ads customer ID is missing"

    try:
        client = GoogleAdsClient.load_from_dict(
            {
                "developer_token": developer_token,
                "json_key_file_path": str(path),
                "use_proto_plus": True,
            }
        )
        ga_service = client.get_service("GoogleAdsService")
        request = client.get_type("SearchGoogleAdsRequest")
        request.customer_id = normalized_customer_id
        request.query = "SELECT customer.id FROM customer LIMIT 1"
        iterator = ga_service.search(request=request)
        next(iter(iterator), None)
        logger.info(
            "google_ads_credentials_validation_query_success filename=%s customer_id=%s",
            path.name,
            normalized_customer_id,
        )
        return True, None
    except Exception as exc:
        logger.warning(
            "google_ads_credentials_validation_query_failed filename=%s customer_id=%s error=%s",
            path.name,
            normalized_customer_id,
            str(exc),
        )
        return False, f"Google Ads credentials do not have access to customer {normalized_customer_id}: {exc}"


def _resolve_google_ads_status() -> dict[str, Any]:
    return _resolve_credentials_status(
        env_key=_GOOGLE_ADS_ENV_KEY,
        default_path=_GOOGLE_ADS_CREDENTIALS_PATH,
        validator=_validate_google_ads_credentials_json,
        status_log_event="google_ads_credentials_status_checked",
    )


def _mask_google_ads_developer_token(value: str) -> str:
    clean = (value or "").strip()
    if not clean:
        return "********"
    suffix = clean[-4:] if len(clean) >= 4 else "*"
    return f"********{suffix}"


def _sanitize_google_test_details(details: Optional[str]) -> Optional[str]:
    if not details:
        return None
    text = str(details)
    replacements = (
        (str(_GA4_CREDENTIALS_PATH), _GA4_CREDENTIALS_PATH.name),
        (str(_GSC_CREDENTIALS_PATH), _GSC_CREDENTIALS_PATH.name),
        (str(_GOOGLE_ADS_CREDENTIALS_PATH), _GOOGLE_ADS_CREDENTIALS_PATH.name),
        (str(_GOOGLE_CREDENTIALS_DIR), "credentials"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _google_integrations_settings_payload() -> dict[str, Any]:
    ga4_property_id = (os.getenv(_GA4_PROPERTY_ENV_KEY) or "").strip()
    gsc_site_url = (os.getenv(_GSC_SITE_URL_ENV_KEY) or "").strip()
    google_ads_developer_token = (os.getenv(_GOOGLE_ADS_DEVELOPER_TOKEN_ENV_KEY) or "").strip()
    google_ads_customer_id = (os.getenv(_GOOGLE_ADS_CUSTOMER_ID_ENV_KEY) or "").strip()
    return {
        "success": True,
        "settings": {
            "ga4_property_id": {
                "value": ga4_property_id or None,
                "configured": bool(ga4_property_id),
            },
            "gsc_site_url": {
                "value": gsc_site_url or None,
                "configured": bool(gsc_site_url),
            },
            "google_ads_developer_token": {
                "configured": bool(google_ads_developer_token),
                "masked_value": _mask_google_ads_developer_token(google_ads_developer_token)
                if google_ads_developer_token
                else None,
            },
            "google_ads_customer_id": {
                "value": google_ads_customer_id or None,
                "configured": bool(google_ads_customer_id),
            },
        },
    }


@router.get("/integrations/google/settings")
def get_google_integrations_settings(
    _verified: str = Depends(verify_admin_key),
):
    return _google_integrations_settings_payload()


@router.post("/integrations/google/settings")
def update_google_integrations_settings(
    body: GoogleIntegrationsSettingsUpdateBody = Body(...),
    _verified: str = Depends(verify_admin_key),
):
    update_map = {
        _GA4_PROPERTY_ENV_KEY: body.ga4_property_id,
        _GSC_SITE_URL_ENV_KEY: body.gsc_site_url,
        _GOOGLE_ADS_DEVELOPER_TOKEN_ENV_KEY: body.google_ads_developer_token,
        _GOOGLE_ADS_CUSTOMER_ID_ENV_KEY: body.google_ads_customer_id,
    }
    updated_fields: list[str] = []
    for env_key, raw_value in update_map.items():
        if raw_value is None:
            continue
        value = raw_value.strip()
        if not value:
            continue
        persist_env_var_value(env_key, value)
        os.environ[env_key] = value
        updated_fields.append(env_key)

    payload = _google_integrations_settings_payload()
    payload["updated_fields"] = updated_fields
    return payload


def _required_google_companion_settings_present(integration_key: str) -> bool:
    if integration_key == "ga4":
        return bool((os.getenv(_GA4_PROPERTY_ENV_KEY) or "").strip())
    if integration_key == "gsc":
        return bool((os.getenv(_GSC_SITE_URL_ENV_KEY) or "").strip())
    if integration_key == "google_ads":
        developer_token = (os.getenv(_GOOGLE_ADS_DEVELOPER_TOKEN_ENV_KEY) or "").strip()
        customer_id = (os.getenv(_GOOGLE_ADS_CUSTOMER_ID_ENV_KEY) or "").strip()
        return bool(developer_token and customer_id)
    return False


def _google_status_payload_for_integration(integration: str) -> dict[str, Any]:
    summary = _build_google_integrations_summary_payload()
    integrations = summary["integrations"]
    row = integrations.get(integration)
    if not isinstance(row, dict):
        return {
            "configured": False,
            "uploaded": False,
            "valid": False,
            "error": "Integration is not recognized.",
        }
    return row


def _to_unified_google_integration_status(integration_key: str, status: dict[str, Any]) -> dict[str, Any]:
    uploaded = bool(status.get("uploaded"))
    valid = bool(status.get("valid"))
    configured = uploaded and _required_google_companion_settings_present(integration_key)
    return {
        "configured": configured,
        "uploaded": uploaded,
        "valid": valid,
        "filename": status.get("filename"),
        "error": status.get("error"),
        "env_key": status.get("env_key"),
    }


def _build_google_integrations_summary_payload() -> dict[str, Any]:
    ga4_status = _resolve_ga4_status()
    gsc_status = _resolve_gsc_status()
    google_ads_status = _resolve_google_ads_status()

    integrations = {
        "ga4": _to_unified_google_integration_status("ga4", ga4_status),
        "gsc": _to_unified_google_integration_status("gsc", gsc_status),
        "google_ads": _to_unified_google_integration_status("google_ads", google_ads_status),
    }
    rows = list(integrations.values())
    total = len(rows)
    valid_count = sum(1 for row in rows if row["valid"])
    missing_count = sum(1 for row in rows if (not row["uploaded"]) or (not row["configured"]))
    invalid_count = max(0, total - valid_count - missing_count)

    if valid_count == total:
        overall_status = "ready"
    elif invalid_count > 0:
        overall_status = "error"
    else:
        overall_status = "incomplete"

    return {
        "success": True,
        "overall_status": overall_status,
        "integrations": integrations,
        "summary": {
            "total": total,
            "valid": valid_count,
            "invalid": invalid_count,
            "missing": missing_count,
        },
    }


@router.get("/integrations/google/status")
def get_google_integrations_status(
    _verified: str = Depends(verify_admin_key),
):
    return _build_google_integrations_summary_payload()


def _google_integration_label(integration: str) -> str:
    if integration == "ga4":
        return "GA4"
    if integration == "gsc":
        return "Search Console"
    if integration == "google_ads":
        return "Google Ads"
    return integration


def _is_validation_unavailable_error(error: Optional[str]) -> bool:
    message = (error or "").strip().lower()
    return "validation is unavailable in this build" in message or "validation is not yet available in this build" in message


def _missing_setting_message(integration: str) -> str:
    if integration == "ga4":
        return "GA4 property ID is missing"
    if integration == "gsc":
        return "Search Console site URL is missing"
    if integration == "google_ads":
        developer_token = (os.getenv(_GOOGLE_ADS_DEVELOPER_TOKEN_ENV_KEY) or "").strip()
        customer_id = (os.getenv(_GOOGLE_ADS_CUSTOMER_ID_ENV_KEY) or "").strip()
        if not developer_token:
            return "Google Ads developer token is missing"
        if not customer_id:
            return "Google Ads customer ID is missing"
        return "Google Ads settings are incomplete"
    return "Required settings are missing"


def _build_google_integration_test_response(
    *,
    integration: str,
    status_payload: dict[str, Any],
) -> dict[str, Any]:
    valid = bool(status_payload.get("valid"))
    uploaded = bool(status_payload.get("uploaded"))
    configured = bool(status_payload.get("configured"))
    error = (status_payload.get("error") or "").strip()

    if valid:
        message = f"{_google_integration_label(integration)} integration is working."
    elif not uploaded:
        message = f"{_google_integration_label(integration)} credentials are missing. Upload credentials first."
    elif not configured:
        message = _missing_setting_message(integration)
    elif _is_validation_unavailable_error(error):
        message = (
            f"{_google_integration_label(integration)} credentials are configured, "
            "but live validation is unavailable in this runtime."
        )
    else:
        message = f"{_google_integration_label(integration)} validation failed."

    return {
        "success": valid,
        "integration": integration,
        "valid": valid,
        "message": message,
        "details": _sanitize_google_test_details(error or None),
    }


def _to_google_readiness_item(integration: str, data: dict[str, Any]) -> dict[str, Any]:
    title = _google_integration_label(integration)
    uploaded = bool(data.get("uploaded"))
    configured = bool(data.get("configured"))
    valid = bool(data.get("valid"))
    error = (data.get("error") or "").strip()

    if valid:
        status = "ready"
        message = f"{title} is configured and validated."
        action_label = "Ready"
    elif not uploaded:
        status = "missing_upload"
        message = f"{title} credentials are not uploaded."
        action_label = "Upload credentials"
    elif not configured:
        status = "missing_setting"
        message = _missing_setting_message(integration)
        action_label = "Complete settings"
    elif _is_validation_unavailable_error(error):
        status = "validation_unavailable"
        message = error or f"{title} validation dependency is unavailable in this build."
        action_label = "Validation dependency missing"
    else:
        status = "invalid"
        message = error or f"{title} validation failed."
        action_label = "Fix access or credentials"

    return {
        "integration": integration,
        "status": status,
        "title": title,
        "message": message,
        "action_label": action_label,
    }


def _derive_google_readiness_next_action(items: list[dict[str, Any]]) -> Optional[str]:
    if all(item["status"] == "ready" for item in items):
        return None

    missing_upload_titles = [item["title"] for item in items if item["status"] == "missing_upload"]
    if missing_upload_titles:
        return "Upload credentials for: " + ", ".join(missing_upload_titles)

    missing_setting_titles = [item["title"] for item in items if item["status"] == "missing_setting"]
    if missing_setting_titles:
        return "Complete required settings for: " + ", ".join(missing_setting_titles)

    invalid_titles = [item["title"] for item in items if item["status"] == "invalid"]
    if invalid_titles:
        return "Fix access or credentials for: " + ", ".join(invalid_titles)

    validation_unavailable_titles = [item["title"] for item in items if item["status"] == "validation_unavailable"]
    if validation_unavailable_titles:
        return "Install missing validation dependencies for: " + ", ".join(validation_unavailable_titles)

    return "Review Google integration setup."


def get_google_integrations_readiness_payload() -> dict[str, Any]:
    summary_payload = _build_google_integrations_summary_payload()
    integrations = summary_payload["integrations"]
    items = [
        _to_google_readiness_item("ga4", integrations["ga4"]),
        _to_google_readiness_item("gsc", integrations["gsc"]),
        _to_google_readiness_item("google_ads", integrations["google_ads"]),
    ]
    return {
        "success": True,
        "overall_status": summary_payload["overall_status"],
        "next_action": _derive_google_readiness_next_action(items),
        "items": items,
    }


def _build_google_readiness_message(payload: dict[str, Any]) -> str:
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        return "Google integrations readiness could not be determined."

    status_by_integration: dict[str, dict[str, Any]] = {}
    for item in items:
        if isinstance(item, dict):
            key = str(item.get("integration") or "").strip()
            if key:
                status_by_integration[key] = item

    ordered_keys = ("ga4", "gsc", "google_ads")
    ready_bits: list[str] = []
    issue_bits: list[str] = []

    for key in ordered_keys:
        item = status_by_integration.get(key)
        if not item:
            continue
        title = str(item.get("title") or _google_integration_label(key))
        status = str(item.get("status") or "").strip()
        message = str(item.get("message") or "").strip()
        if status == "ready":
            ready_bits.append(f"{title} is ready")
        elif status == "missing_upload":
            issue_bits.append(f"{title} credentials have not been uploaded")
        elif status == "missing_setting":
            issue_bits.append(message or f"{title} settings are incomplete")
        elif status == "validation_unavailable":
            issue_bits.append(
                f"{title} credentials are present but runtime validation support is missing"
            )
        else:
            issue_bits.append(message or f"{title} validation failed")

    overall = str(payload.get("overall_status") or "").strip()
    if overall == "ready":
        return "All Google integrations are ready."

    if overall == "error" and len(issue_bits) == 1 and "Google Ads" in issue_bits[0]:
        return issue_bits[0] + ", so Google-dependent actions should stay blocked until access is fixed."

    if issue_bits:
        lead = "Google integrations are not fully ready."
        details = ", ".join(ready_bits + issue_bits)
        return f"{lead} {details[0].upper() + details[1:] if details else ''}".strip()

    return "Google integrations are not fully ready."


@router.get("/integrations/google/readiness")
def get_google_integrations_readiness(
    _verified: str = Depends(verify_admin_key),
):
    return get_google_integrations_readiness_payload()


@router.get("/integrations/google/readiness/message")
def get_google_integrations_readiness_message(
    _verified: str = Depends(verify_admin_key),
):
    payload = get_google_integrations_readiness_payload()
    return {
        "success": True,
        "message": _build_google_readiness_message(payload),
        "overall_status": payload["overall_status"],
        "next_action": payload["next_action"],
        "items": payload["items"],
    }


@router.post("/integrations/google/ga4/test")
def test_google_ga4_integration(
    _verified: str = Depends(verify_admin_key),
):
    payload = _google_status_payload_for_integration("ga4")
    return _build_google_integration_test_response(
        integration="ga4",
        status_payload=payload,
    )


@router.post("/integrations/google/gsc/test")
def test_google_gsc_integration(
    _verified: str = Depends(verify_admin_key),
):
    payload = _google_status_payload_for_integration("gsc")
    return _build_google_integration_test_response(
        integration="gsc",
        status_payload=payload,
    )


@router.post("/integrations/google/google-ads/test")
def test_google_ads_integration(
    _verified: str = Depends(verify_admin_key),
):
    payload = _google_status_payload_for_integration("google_ads")
    return _build_google_integration_test_response(
        integration="google_ads",
        status_payload=payload,
    )


def compute_admin_secrets_status_dict() -> dict:
    """Shared JSON for secrets banner (GET /api/admin/secrets-status and monitoring alias)."""
    try:
        from app.services.required_secrets_registry import evaluate_requirements

        return evaluate_requirements()
    except Exception as exc:
        logger.warning("compute_admin_secrets_status_dict: registry unavailable: %s", type(exc).__name__)
        try:
            from app.core.environment import is_atp_trading_only, is_aws as _is_aws
        except Exception:

            def _is_aws() -> bool:
                return False

            def is_atp_trading_only() -> bool:
                return False

        return {
            "overall": "ok",
            "missing": [],
            "skipped_count": 0,
            "context": {
                "atp_trading_only": bool(is_atp_trading_only()),
                "environment": (os.getenv("ENVIRONMENT") or "unknown").strip(),
                "aws": bool(_is_aws()),
                "github_legacy_pat_active": (os.getenv("ALLOW_LEGACY_GITHUB_PAT") or "").lower() in ("1", "true", "yes"),
                "github_app_client_id_status": None,
            },
            "automation_readiness": {
                "applicable": False,
                "missing": [],
                "note": "Secrets registry is not available on this server build.",
            },
        }


@router.get("/admin/secrets-status")
def admin_secrets_status(admin_key: str = Depends(verify_admin_key)):
    """Return required-secrets evaluation for the trading dashboard (admin-only)."""
    return compute_admin_secrets_status_dict()


def compute_admin_recovery_dict() -> dict:
    try:
        from app.services.secret_recovery import recovery_status_payload

        return recovery_status_payload()
    except Exception as exc:
        logger.warning("compute_admin_recovery_dict: %s", type(exc).__name__)
        return {
            "auto_restart_enabled": False,
            "compose_project_configured": False,
            "recovery_runnable": False,
            "note": "Recovery module unavailable on this build.",
        }


@router.get("/admin/recovery-status")
def admin_recovery_status(admin_key: str = Depends(verify_admin_key)):
    return compute_admin_recovery_dict()


def perform_secrets_intake(body: SecretIntakeBody) -> dict:
    """
    Persist one allowlisted env var to runtime.env (shared by /admin and /monitoring routes).
    Caller must have verified X-Admin-Key already.
    """
    from app.jarvis.secure_runtime_env_write import persist_env_var_value

    key = (body.env_var or "").strip()
    val = (body.value or "").strip()
    if not key or not val:
        raise HTTPException(status_code=400, detail="env_var_and_value_required")

    try:
        from app.services.required_secrets_registry import is_allowed_intake_key
    except Exception:

        def is_allowed_intake_key(name: str) -> bool:  # type: ignore[misc]
            return name in ("GITHUB_APP_CLIENT_ID",)

    if not is_allowed_intake_key(key):
        raise HTTPException(status_code=400, detail="env_var_not_allowed_for_intake")

    if body.persist_ssm:
        logger.info("secrets_intake persist_ssm=1 for %s (SSM path optional; runtime.env always updated)", key)

    try:
        persist_env_var_value(key, val)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except OSError as exc:
        logger.error("secrets_intake persist OSError env_var=%s: %s", key, exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="runtime_env_write_failed (check permissions on secrets/ and runtime.env)",
        ) from exc

    os.environ[key] = val
    return {"ok": True, "message": "Saved to runtime.env"}


@router.post("/admin/secrets-intake")
def admin_secrets_intake(
    body: SecretIntakeBody = Body(...),
    _verified: str = Depends(verify_admin_key),
):
    """Persist one allowlisted env var to runtime.env (admin-only)."""
    return perform_secrets_intake(body)


@router.post("/upload/ga4-credentials")
async def upload_ga4_credentials(
    ga4_credentials: UploadFile = File(...),
    _verified: str = Depends(verify_admin_key),
):
    """Upload and validate GA4 service account JSON credentials."""
    try:
        raw = await _validate_uploaded_json_file(ga4_credentials)
        _write_credentials_file_atomically(_GA4_CREDENTIALS_PATH, raw)

        persist_env_var_value(_GA4_ENV_KEY, str(_GA4_CREDENTIALS_PATH))
        os.environ[_GA4_ENV_KEY] = str(_GA4_CREDENTIALS_PATH)

        logger.info(
            "ga4_credentials_upload_success target=%s size_bytes=%d",
            str(_GA4_CREDENTIALS_PATH),
            len(raw),
        )
        return _resolve_ga4_status()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("ga4_credentials_upload_failed err=%s", type(exc).__name__)
        return _build_credentials_status_payload(
            env_key=_GA4_ENV_KEY,
            success=False,
            uploaded=False,
            valid=False,
            filename=None,
            error=f"Upload failed: {exc}",
        )


@router.get("/upload/ga4-credentials/status")
def get_ga4_credentials_status(
    _verified: str = Depends(verify_admin_key),
):
    return _resolve_ga4_status()


@router.post("/upload/gsc-credentials")
async def upload_gsc_credentials(
    gsc_credentials: UploadFile = File(...),
    _verified: str = Depends(verify_admin_key),
):
    """Upload and validate Search Console service account JSON credentials."""
    try:
        raw = await _validate_uploaded_json_file(gsc_credentials)
        _write_credentials_file_atomically(_GSC_CREDENTIALS_PATH, raw)

        persist_env_var_value(_GSC_ENV_KEY, str(_GSC_CREDENTIALS_PATH))
        os.environ[_GSC_ENV_KEY] = str(_GSC_CREDENTIALS_PATH)

        logger.info(
            "gsc_credentials_upload_success target=%s size_bytes=%d",
            str(_GSC_CREDENTIALS_PATH),
            len(raw),
        )
        return _resolve_gsc_status()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("gsc_credentials_upload_failed err=%s", type(exc).__name__)
        return _build_credentials_status_payload(
            env_key=_GSC_ENV_KEY,
            success=False,
            uploaded=False,
            valid=False,
            filename=None,
            error=f"Upload failed: {exc}",
        )


@router.get("/upload/gsc-credentials/status")
def get_gsc_credentials_status(
    _verified: str = Depends(verify_admin_key),
):
    return _resolve_gsc_status()


@router.post("/upload/google-ads-credentials")
async def upload_google_ads_credentials(
    google_ads_credentials: UploadFile = File(...),
    _verified: str = Depends(verify_admin_key),
):
    """Upload and validate Google Ads service account JSON credentials."""
    try:
        raw = await _validate_uploaded_json_file(google_ads_credentials)
        _write_credentials_file_atomically(_GOOGLE_ADS_CREDENTIALS_PATH, raw)

        persist_env_var_value(_GOOGLE_ADS_ENV_KEY, str(_GOOGLE_ADS_CREDENTIALS_PATH))
        os.environ[_GOOGLE_ADS_ENV_KEY] = str(_GOOGLE_ADS_CREDENTIALS_PATH)

        logger.info(
            "google_ads_credentials_upload_success target=%s size_bytes=%d",
            str(_GOOGLE_ADS_CREDENTIALS_PATH),
            len(raw),
        )
        return _resolve_google_ads_status()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("google_ads_credentials_upload_failed err=%s", type(exc).__name__)
        return _build_credentials_status_payload(
            env_key=_GOOGLE_ADS_ENV_KEY,
            success=False,
            uploaded=False,
            valid=False,
            filename=None,
            error=f"Upload failed: {exc}",
        )


@router.get("/upload/google-ads-credentials/status")
def get_google_ads_credentials_status(
    _verified: str = Depends(verify_admin_key),
):
    return _resolve_google_ads_status()


@router.post("/admin/recovery-apply")
def admin_recovery_apply(admin_key: str = Depends(verify_admin_key)):
    try:
        from app.services.secret_recovery import apply_backend_recovery
    except Exception:
        raise HTTPException(
            status_code=501,
            detail="secret_recovery_not_available_on_this_build",
        ) from None
    try:
        return apply_backend_recovery()
    except Exception as exc:
        logger.error("admin_recovery_apply failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="recovery_apply_failed") from exc


@router.post("/admin/rotate-admin-key")
def rotate_admin_key(
    body: RotateAdminKeyBody = Body(...),
    admin_key: str = Depends(verify_admin_key),
):
    """
    Rotate ADMIN_ACTIONS_KEY: verifies current X-Admin-Key, writes new value to runtime.env,
    and updates the running process environment so the session can continue without restart.
    """
    from app.jarvis.secure_runtime_env_write import persist_env_var_value

    new_k = (body.new_admin_key or "").strip()
    if len(new_k) < _MIN_ADMIN_KEY_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"new_admin_key_too_short (min {_MIN_ADMIN_KEY_LEN} characters)",
        )
    if new_k == admin_key:
        raise HTTPException(status_code=400, detail="new_admin_key_same_as_current")

    try:
        persist_env_var_value("ADMIN_ACTIONS_KEY", new_k)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve

    os.environ["ADMIN_ACTIONS_KEY"] = new_k
    logger.info("ADMIN_ACTIONS_KEY rotated via /admin/rotate-admin-key")
    return {"ok": True, "message": "Admin key updated. Use the new key from now on (also saved to runtime.env)."}


@router.post("/admin/test-telegram")
async def test_telegram(
    admin_key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db)
):
    """
    Send a test Telegram message (admin-only, rate-limited)
    
    Requires:
    - Header: X-Admin-Key: <ADMIN_ACTIONS_KEY>
    
    Returns:
    - {"ok": true} on success
    - {"ok": false, "error": "<reason>"} on failure
    """
    global _last_test_telegram_ts
    
    # Rate limiting check
    now = time.time()
    if _last_test_telegram_ts is not None:
        time_since_last = now - _last_test_telegram_ts
        if time_since_last < _TEST_TELEGRAM_COOLDOWN_SECONDS:
            remaining = int(_TEST_TELEGRAM_COOLDOWN_SECONDS - time_since_last)
            logger.warning(f"Test telegram rate limited (cooldown: {remaining}s remaining)")
            raise HTTPException(
                status_code=429,
                detail=f"rate_limited (cooldown: {remaining}s remaining)"
            )
    
    try:
        # Send test message
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        message = f"✅ TEST: Telegram is working (AWS) — {timestamp}"
        
        if not telegram_notifier.enabled:
            return {"ok": False, "error": "telegram_disabled"}
        
        success = telegram_notifier.send_message(message, origin="AWS")
        record_telegram_send_result(success)
        
        if success:
            _last_test_telegram_ts = now
            logger.info("Test Telegram message sent successfully")
            return {"ok": True}
        else:
            return {"ok": False, "error": "send_failed"}
    
    except Exception as e:
        logger.error(f"Error sending test Telegram message: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


@router.post("/admin/telegram/atp-control-token")
def update_atp_control_telegram_token(
    body: TelegramTokenUpdateBody = Body(...),
    admin_key: str = Depends(verify_admin_key),
):
    """
    Admin-only: update ATP Control Telegram bot token in PROD SSM and refresh runtime.
    Never logs or returns full token.
    """
    token = (body.token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="token_required")
    if not _validate_telegram_token_shape(token):
        raise HTTPException(status_code=400, detail="invalid_telegram_token_format")

    masked = _mask_token_suffix(token)
    try:
        import boto3

        ssm = boto3.client("ssm", region_name=_PROD_REGION)
        ssm.put_parameter(
            Name=_PROD_TELEGRAM_TOKEN_PARAM,
            Value=token,
            Type="SecureString",
            Overwrite=True,
        )

        ok, err = _run_prod_runtime_refresh_via_ssm(ssm)
        if not ok:
            logger.error(
                "telegram_token_update_failed mask=%s reason=%s",
                masked,
                err[:200],
            )
            raise HTTPException(status_code=500, detail=f"runtime_refresh_failed ({err[:120]})")

        logger.info(
            "telegram_token_update_success mask=%s param=%s",
            masked,
            _PROD_TELEGRAM_TOKEN_PARAM,
        )
        return {
            "ok": True,
            "message": "ATP Control Telegram token updated",
            "token_masked": masked,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("telegram_token_update_error mask=%s err=%s", masked, str(e)[:200], exc_info=True)
        raise HTTPException(status_code=500, detail="token_update_failed")


@router.post("/admin/debug/evaluate-symbol")
def evaluate_symbol(
    body: EvaluateSymbolBody = Body(...),
    admin_key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """
    Trigger signal evaluation for one symbol (admin-only, for smoke/E2E).
    Requires X-Admin-Key header. Writes to watchlist_signal_state and may send Telegram.
    """
    symbol = (body.symbol or "BTC_USDT").strip().upper()
    try:
        watchlist_item = (
            db.query(WatchlistItem)
            .filter(WatchlistItem.symbol == symbol, WatchlistItem.is_deleted == False)
            .first()
        )
        if not watchlist_item:
            return {"ok": False, "error": f"symbol_not_in_watchlist:{symbol}"}
        signal_monitor_service._check_signal_for_coin_sync(db, watchlist_item)
        return {"ok": True, "symbol": symbol}
    except Exception as e:
        logger.warning(f"evaluate-symbol {symbol}: {e}", exc_info=True)
        return {"ok": False, "error": str(e), "symbol": symbol}



