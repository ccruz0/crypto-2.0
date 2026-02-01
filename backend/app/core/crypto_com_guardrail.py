"""
Guardrail: ensure Crypto.com private API calls originate from AWS or via SSH SOCKS.
When CRYPTOCOM_FORCE_AWS=1, local direct calls abort; SSH-proxied or AWS allowed.
EXECUTION_CONTEXT env var (LOCAL | AWS) drives script behavior: LOCAL = skip private auth.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Literal, Optional

logger = logging.getLogger(__name__)

ContextKind = Literal["AWS", "LOCAL_VIA_SSH_PROXY", "LOCAL"]

# Standard message for 40101 when running on AWS (egress IP not allowlisted)
AUTH_40101_MESSAGE = (
    "Authentication failure: AWS egress IP not allowlisted for this API key"
)

# Skip payload returned when EXECUTION_CONTEXT != AWS and private API would be called
# Mandatory structure everywhere: skipped, reason, label
SKIP_PAYLOAD_KEYS = ("skipped", "reason", "label")
SKIP_REASON = "LOCAL mode: private Crypto.com endpoints are AWS-only"


def _skip_payload(label: str) -> dict:
    """Build the standard skip payload (single canonical shape)."""
    return {
        "skipped": True,
        "reason": SKIP_REASON,
        "label": label,
    }


def require_aws_or_skip(label: str) -> "Optional[dict]":
    """
    When EXECUTION_CONTEXT is not AWS, return the standard skip payload so callers
    do not build nonce/sig or send private API requests. When AWS, return None (proceed).
    """
    if get_execution_context() == "AWS":
        return None
    return _skip_payload(label)


def _is_socks_proxy() -> bool:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        v = (os.getenv(name) or "").strip()
        if v.lower().startswith("socks5"):
            return True
    return False


def _is_aws() -> bool:
    if os.getenv("AWS_EXECUTION_ENV"):
        return True
    try:
        p = "/sys/hypervisor/uuid"
        if os.path.isfile(p):
            with open(p) as f:
                first = (f.read() or "").strip()
                if "ec2" in first.lower():
                    return True
    except OSError:
        pass
    try:
        import urllib.request
        req = urllib.request.Request("http://169.254.169.254/latest/meta-data/", method="GET")
        urllib.request.urlopen(req, timeout=1)
        return True
    except Exception:
        pass
    return False


def get_execution_context() -> ContextKind:
    # Explicit env wins: EXECUTION_CONTEXT=AWS or LOCAL
    ctx_env = (os.getenv("EXECUTION_CONTEXT") or "").strip().upper()
    if ctx_env == "AWS":
        return "AWS"
    if ctx_env == "LOCAL":
        return "LOCAL"
    if _is_aws():
        return "AWS"
    if _is_socks_proxy():
        return "LOCAL_VIA_SSH_PROXY"
    return "LOCAL"


def is_local_execution_context() -> bool:
    """True when private API must be skipped (LOCAL); use for auth/verification scripts."""
    return get_execution_context() == "LOCAL"


# Message used in skip payload and script printouts (same as SKIP_REASON)
LOCAL_SKIP_PRIVATE_MESSAGE = SKIP_REASON


def enforce_crypto_com_origin(*, _log=logger) -> None:
    """
    If CRYPTOCOM_FORCE_AWS=1: abort when context is LOCAL; allow AWS and LOCAL_VIA_SSH_PROXY.
    When LOCAL_VIA_SSH_PROXY, log a warning. No-op when CRYPTOCOM_FORCE_AWS is not 1.
    """
    if os.getenv("CRYPTOCOM_FORCE_AWS", "").strip() != "1":
        return
    ctx = get_execution_context()
    if ctx == "AWS":
        return
    if ctx == "LOCAL_VIA_SSH_PROXY":
        _log.warning(
            "CRYPTOCOM_FORCE_AWS=1: traffic is routed via SOCKS proxy (debug-only). "
            "Ensure HTTP_PROXY/HTTPS_PROXY point to your SSH SOCKS tunnel."
        )
        return
    msg = (
        "CRYPTOCOM_FORCE_AWS=1 but execution context is LOCAL. "
        "Crypto.com Exchange API keys are IP-whitelisted; direct local calls will get 40101. "
        "Route traffic through AWS (run there) or use an SSH SOCKS proxy (HTTP_PROXY/HTTPS_PROXY=socks5://...). "
        "See README-ops.md: 'Routing Crypto.com traffic through AWS using SSH'."
    )
    print(msg, file=sys.stderr)
    sys.exit(1)
