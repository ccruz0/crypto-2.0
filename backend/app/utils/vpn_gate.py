"""
API Reachability Gate: Check external API (Crypto.com) reachability before startup
NOTE: This is NOT a VPN - it's just a health check to verify connectivity to Crypto.com API.
The system connects directly to Crypto.com Exchange via AWS Elastic IP without VPN.
"""
import os
import time
import json
import urllib.request
import urllib.error
import asyncio
import logging
from typing import Optional

from app.utils.egress_guard import validate_outbound_url, EgressGuardError

logger = logging.getLogger(__name__)

ENABLED = os.getenv("VPN_GATE_ENABLED", "true").lower() == "true"
URL = os.getenv("VPN_GATE_URL", "https://api.crypto.com/v2/public/get-ticker?instrument_name=BTC_USDT")
TIMEOUT = int(os.getenv("VPN_GATE_TIMEOUT_SECS", "3"))
RETRY = int(os.getenv("VPN_GATE_RETRY_SECS", "5"))
MAXWAIT = int(os.getenv("VPN_GATE_MAX_WAIT_SECS", "120"))
BG = os.getenv("VPN_GATE_BACKGROUND", "true").lower() == "true"
ENV = os.getenv("ENVIRONMENT", "dev").lower()
DEV_MAX = int(os.getenv("VPN_GATE_DEV_MAX_WAIT_SECS", "15"))

# Validate URL at module load time
try:
    validated_url, _ = validate_outbound_url(URL, calling_module="vpn_gate.module_init")
    if validated_url != URL:
        logger.warning(f"[VPN_GATE] URL normalized: {URL} -> {validated_url}")
    URL = validated_url
except EgressGuardError as e:
    logger.error(f"[VPN_GATE] SECURITY: Invalid VPN_GATE_URL configured: {e}")
    # Disable VPN gate if URL is invalid
    ENABLED = False
    URL = ""  # Set to empty string to prevent use

# Module-level status flag
_vpn_ok: bool = False
_last_error: Optional[str] = None


def get_vpn_ok() -> bool:
    """Get current VPN reachability status"""
    return _vpn_ok


def get_vpn_last_error() -> Optional[str]:
    """Get last VPN check error message"""
    return _last_error


def _http_ok() -> bool:
    """Internal HTTP check function"""
    global _last_error
    try:
        # Validate URL before making request (defense in depth)
        try:
            validated_url, _ = validate_outbound_url(URL, calling_module="vpn_gate._http_ok")
        except EgressGuardError as e:
            _last_error = f"Egress guard blocked: {str(e)}"
            logger.error(f"[VPN_GATE] {_last_error}")
            return False
        
        req = urllib.request.Request(validated_url)
        req.add_header("User-Agent", "gluetun-vpn-gate/1.0")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            if r.status != 200:
                _last_error = f"HTTP {r.status}"
                return False
            if os.getenv("VPN_GATE_EXPECTS_JSON", "true").lower() == "true":
                try:
                    data = r.read(2048).decode("utf-8", "ignore")
                    json.loads(data)
                except Exception as e:
                    _last_error = f"Invalid JSON: {str(e)[:100]}"
                    return False
        _last_error = None
        return True
    except urllib.error.HTTPError as e:
        _last_error = f"HTTP {e.code}: {e.reason[:100]}"
        return False
    except urllib.error.URLError as e:
        _last_error = f"URL Error: {str(e)[:200]}"
        return False
    except Exception as e:
        _last_error = str(e)[:200]
        return False


def check_once() -> bool:
    """Check if external API is reachable once"""
    return _http_ok()


def wait_until_ok(logger=None) -> bool:
    """Legacy blocking mode (kept for compatibility)."""
    if not ENABLED:
        return True

    start = time.time()
    max_wait = DEV_MAX if ENV == "dev" else MAXWAIT
    while True:
        if _http_ok():
            global _vpn_ok
            _vpn_ok = True
            if logger:
                logger.info("vpn_gate: OK reachability to %s", URL)
            return True
        waited = int(time.time() - start)
        if waited >= max_wait:
            _vpn_ok = False
            if logger:
                logger.warning(
                    "vpn_gate: timed out after %ss waiting for %s", waited, URL
                )
            return False
        if logger:
            logger.info(
                "vpn_gate: waiting... (%ss/%ss) last_error=%s",
                waited,
                max_wait,
                _last_error,
            )
        time.sleep(RETRY)


async def monitor(logger=None):
    """Non-blocking background monitor. Sets _vpn_ok continuously."""
    if not ENABLED:
        if logger:
            logger.info("vpn_gate: disabled via env")
        return

    # Quick settle loop (shorter in dev)
    settle_deadline = time.time() + (DEV_MAX if ENV == "dev" else MAXWAIT)
    global _vpn_ok

    while True:
        ok = await asyncio.to_thread(_http_ok)
        _vpn_ok = ok

        if logger:
            logger.info(
                "vpn_gate: status=%s url=%s last_error=%s", ok, URL, _last_error
            )

        # After initial settle window, reduce chatter
        if time.time() < settle_deadline:
            await asyncio.sleep(RETRY)
        else:
            await asyncio.sleep(max(RETRY, 15))

