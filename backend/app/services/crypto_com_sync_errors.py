"""Classify Crypto.com private API responses for open-orders sync."""

from __future__ import annotations

from typing import Any, Optional

AUTH_ERROR_CODES = frozenset({40101, 40103})


def map_error_code_to_sync_status(error_code: Optional[int]) -> str:
    if error_code is None:
        return "api_error"
    if error_code in AUTH_ERROR_CODES:
        return "failed_auth"
    return "api_error"


def build_private_api_error(
    *,
    sync_status: str,
    error_message: str,
    error_code: Optional[int] = None,
) -> dict[str, Any]:
    """Structured failure payload — never includes verified empty ``data``."""
    return {
        "error": error_message,
        "error_code": error_code,
        "error_message": error_message,
        "sync_status": sync_status,
        "data_verified": False,
    }


def build_private_api_success(data: list[Any]) -> dict[str, Any]:
    return {
        "data": data,
        "sync_status": "ok",
        "data_verified": True,
        "error_code": None,
        "error_message": None,
    }


def is_sync_failure_response(response: Optional[dict[str, Any]]) -> bool:
    if not response:
        return True
    if response.get("skipped"):
        return True
    if response.get("data_verified") is False:
        return True
    if response.get("sync_status") in {
        "failed_auth",
        "missing_credentials",
        "api_error",
        "stale",
        "skipped",
    }:
        return True
    if response.get("error"):
        return True
    return False


def extract_sync_failure(response: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not response:
        return {
            "sync_status": "api_error",
            "error_code": None,
            "error_message": "Empty response from Crypto.com private API",
        }
    if response.get("skipped"):
        return {
            "sync_status": "skipped",
            "error_code": None,
            "error_message": response.get("reason") or "Private API skipped",
        }
    sync_status = response.get("sync_status")
    if not sync_status and response.get("error"):
        code = response.get("error_code")
        if isinstance(code, str) and code.isdigit():
            code = int(code)
        sync_status = map_error_code_to_sync_status(code if isinstance(code, int) else None)
        if "credentials not configured" in str(response.get("error", "")).lower():
            sync_status = "missing_credentials"
    return {
        "sync_status": sync_status or "api_error",
        "error_code": response.get("error_code"),
        "error_message": response.get("error_message") or response.get("error"),
    }


def parse_http_auth_error(error_data: dict[str, Any]) -> dict[str, Any]:
    error_code = error_data.get("code")
    if isinstance(error_code, str) and error_code.isdigit():
        error_code = int(error_code)
    error_msg = str(error_data.get("message") or "Authentication failure")
    sync_status = map_error_code_to_sync_status(
        error_code if isinstance(error_code, int) else None
    )
    return build_private_api_error(
        sync_status=sync_status,
        error_code=error_code if isinstance(error_code, int) else None,
        error_message=error_msg,
    )
