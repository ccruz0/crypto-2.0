"""
Egress Guard: Enforce outbound allowlist to prevent scanning-like traffic

This module provides centralized validation for all outbound HTTP requests
to ensure they only target approved domains and never raw IP addresses.
"""
import re
import logging
import socket
from typing import Optional, Tuple, Set
from urllib.parse import urlparse
import ipaddress

logger = logging.getLogger(__name__)

# Allowlisted domains (exact matches and subdomains)
ALLOWLISTED_DOMAINS: Set[str] = {
    # Crypto.com Exchange API
    "api.crypto.com",
    # CoinGecko API
    "api.coingecko.com",
    # Telegram Bot API
    "api.telegram.org",
    # IP checking service (for diagnostics)
    "api.ipify.org",
    "icanhazip.com",
    # AWS metadata service (for EC2 instances)
    "169.254.169.254",
    # Our own domains (if any)
    "dashboard.hilovivo.com",
    "hilovivo.com",
}

# IP addresses that are explicitly allowed (metadata services, etc.)
ALLOWLISTED_IPS: Set[str] = {
    "169.254.169.254",  # AWS metadata service
}

# Regex pattern to detect raw IP addresses in URLs
IP_PATTERN = re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?$')


class EgressGuardError(Exception):
    """Raised when an outbound request violates allowlist rules"""
    pass


def is_raw_ip(host: str) -> bool:
    """Check if a host string is a raw IP address"""
    # Remove port if present
    if ':' in host:
        host = host.split(':')[0]
    
    # Check if it matches IP pattern
    if IP_PATTERN.match(host):
        return True
    
    # Try to parse as IP address
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def is_domain_allowed(host: str) -> bool:
    """
    Check if a domain is in the allowlist.
    Supports exact matches and subdomains.
    """
    # Check exact match
    if host in ALLOWLISTED_DOMAINS:
        return True
    
    # Check if it's a subdomain of an allowlisted domain
    for allowed_domain in ALLOWLISTED_DOMAINS:
        # Skip IP addresses in allowlist
        if is_raw_ip(allowed_domain):
            continue
        
        # Check exact match
        if host == allowed_domain:
            return True
        
        # Check subdomain match (e.g., subdomain.api.crypto.com matches api.crypto.com)
        if host.endswith('.' + allowed_domain):
            return True
    
    return False


def validate_outbound_url(url: str, calling_module: str = "unknown") -> Tuple[str, Optional[str]]:
    """
    Validate that an outbound URL is allowed.
    
    Args:
        url: The URL to validate
        calling_module: Name of the module/function making the request (for logging)
    
    Returns:
        Tuple of (normalized_url, resolved_ip) where resolved_ip may be None
    
    Raises:
        EgressGuardError: If the URL violates allowlist rules
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        
        if not host:
            raise EgressGuardError(
                f"Invalid URL (no hostname): {url} "
                f"(called from {calling_module})"
            )
        
        # Allow local/internal addresses (localhost, 127.x.x.x, host.docker.internal, etc.)
        # These are typically used for internal proxy services and are safe
        if any(local in host.lower() for local in [
            "localhost", "127.0.0.1", "0.0.0.0", "::1",
            "host.docker.internal", "docker.internal"
        ]):
            logger.debug(
                f"[EGRESS_GUARD] Allowed local/internal address: {host} "
                f"(called from {calling_module})"
            )
            return url, host.split(':')[0] if ':' in host else host
        
        # Check if it's a raw IP
        if is_raw_ip(host):
            # Check if IP is explicitly allowlisted (e.g., metadata services)
            ip_addr = host.split(':')[0]
            if ip_addr in ALLOWLISTED_IPS:
                logger.info(
                    f"[EGRESS_GUARD] Allowed raw IP: {host} "
                    f"(allowlisted metadata service, called from {calling_module})"
                )
                return url, ip_addr
            
            # Check if it's a private/internal IP range (10.x.x.x, 172.16-31.x.x, 192.168.x.x)
            try:
                ip = ipaddress.ip_address(ip_addr)
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    logger.debug(
                        f"[EGRESS_GUARD] Allowed private/internal IP: {host} "
                        f"(called from {calling_module})"
                    )
                    return url, ip_addr
            except ValueError:
                pass
            
            # Raw public IPs are blocked by default
            error_msg = (
                f"SECURITY VIOLATION: Outbound request to raw IP address {host} blocked. "
                f"URL: {url}, Called from: {calling_module}. "
                f"Raw IP addresses are not allowed for security reasons. "
                f"Use domain names instead."
            )
            logger.error(f"[EGRESS_GUARD] {error_msg}")
            raise EgressGuardError(error_msg)
        
        # Check if domain is allowed
        if not is_domain_allowed(host):
            error_msg = (
                f"SECURITY VIOLATION: Outbound request to non-allowlisted domain {host} blocked. "
                f"URL: {url}, Called from: {calling_module}. "
                f"Domain is not in the egress allowlist. "
                f"If this is legitimate, add it to ALLOWLISTED_DOMAINS in egress_guard.py"
            )
            logger.error(f"[EGRESS_GUARD] {error_msg}")
            raise EgressGuardError(error_msg)
        
        # Domain is allowed - optionally resolve IP for logging (but don't block if resolution fails)
        resolved_ip = None
        try:
            resolved_ip = socket.gethostbyname(host)
            logger.debug(
                f"[EGRESS_GUARD] Allowed outbound request: {host} -> {resolved_ip} "
                f"(called from {calling_module})"
            )
        except socket.gaierror:
            # DNS resolution failed, but we'll allow it (DNS will fail at connection time anyway)
            logger.warning(
                f"[EGRESS_GUARD] DNS resolution failed for {host}, but allowing request "
                f"(called from {calling_module})"
            )
        
        return url, resolved_ip
    
    except EgressGuardError:
        raise
    except Exception as e:
        error_msg = (
            f"Error validating outbound URL {url}: {str(e)} "
            f"(called from {calling_module})"
        )
        logger.error(f"[EGRESS_GUARD] {error_msg}")
        raise EgressGuardError(error_msg)


def log_outbound_request(
    url: str,
    method: str = "GET",
    status_code: Optional[int] = None,
    calling_module: str = "unknown",
    correlation_id: Optional[str] = None
) -> None:
    """
    Log an outbound request for security auditing.
    
    Args:
        url: The URL that was requested
        method: HTTP method (GET, POST, etc.)
        status_code: HTTP status code if available
        calling_module: Name of the module/function making the request
        correlation_id: Optional correlation ID for tracing
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "unknown"
        
        log_msg = (
            f"[EGRESS_GUARD] Outbound {method} to {host} "
            f"(status={status_code}, module={calling_module}"
        )
        if correlation_id:
            log_msg += f", correlation_id={correlation_id}"
        log_msg += ")"
        
        logger.info(log_msg)
    except Exception as e:
        logger.warning(f"[EGRESS_GUARD] Error logging outbound request: {e}")

