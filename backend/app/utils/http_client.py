"""
MANDATORY HTTP CLIENT WRAPPER

This is the ONLY allowed entry point for outbound HTTP requests in the backend.
All outbound HTTP requests MUST go through this module to ensure egress guard
validation is enforced.

DO NOT:
- Use requests.get/post directly
- Use aiohttp.ClientSession directly
- Use urllib.request directly
- Import requests/aiohttp/urllib outside this file

DO:
- Import this module: from app.utils.http_client import http_get, http_post, async_http_get
- Use these functions for all outbound HTTP requests
- All URLs are automatically validated against egress allowlist

Security:
- All URLs are validated before making requests
- Raw IP addresses are blocked
- Non-allowlisted domains are blocked
- All requests are logged for audit
"""
import logging
import time
from typing import Optional, Dict, Any, Tuple
import uuid

from app.utils.egress_guard import (
    validate_outbound_url,
    log_outbound_request,
    EgressGuardError
)

logger = logging.getLogger(__name__)

# Try to import requests (synchronous)
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.warning("requests library not available")

# Try to import aiohttp (async)
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False


def http_get(
    url: str,
    timeout: float = 10.0,
    headers: Optional[Dict[str, str]] = None,
    calling_module: str = "unknown",
    allow_redirects: bool = True,
    **kwargs
) -> requests.Response:
    """
    Synchronous HTTP GET request with egress guard validation.
    
    Args:
        url: The URL to request (must be allowlisted)
        timeout: Request timeout in seconds
        headers: Optional HTTP headers
        calling_module: Name of the calling module (for logging)
        allow_redirects: Whether to follow redirects
        **kwargs: Additional arguments passed to requests.get()
    
    Returns:
        requests.Response object
    
    Raises:
        EgressGuardError: If URL is not allowlisted
        ImportError: If requests library is not available
    """
    if not REQUESTS_AVAILABLE:
        raise ImportError("requests library is required for http_get()")
    
    # Validate URL against egress allowlist
    validated_url, resolved_ip = validate_outbound_url(url, calling_module=calling_module)
    
    # Generate correlation ID for logging
    correlation_id = str(uuid.uuid4())[:8]
    
    # Prepare headers
    request_headers = headers or {}
    
    try:
        # Make the request
        response = requests.get(
            validated_url,
            timeout=timeout,
            headers=request_headers,
            allow_redirects=allow_redirects,
            **kwargs
        )
        
        # Log the request for security audit
        log_outbound_request(
            validated_url,
            method="GET",
            status_code=response.status_code,
            calling_module=calling_module,
            correlation_id=correlation_id
        )
        
        return response
    
    except requests.exceptions.RequestException as e:
        # Log failed requests
        logger.error(
            f"[HTTP_CLIENT] GET request failed: {url} (called from {calling_module}): {e}"
        )
        raise
    except Exception as e:
        logger.error(
            f"[HTTP_CLIENT] Unexpected error in http_get: {url} (called from {calling_module}): {e}"
        )
        raise


def http_post(
    url: str,
    json: Optional[Dict[str, Any]] = None,
    data: Optional[Any] = None,
    timeout: float = 10.0,
    headers: Optional[Dict[str, str]] = None,
    calling_module: str = "unknown",
    **kwargs
) -> requests.Response:
    """
    Synchronous HTTP POST request with egress guard validation.
    
    Args:
        url: The URL to request (must be allowlisted)
        json: Optional JSON data to send
        data: Optional data to send (alternative to json)
        timeout: Request timeout in seconds
        headers: Optional HTTP headers
        calling_module: Name of the calling module (for logging)
        **kwargs: Additional arguments passed to requests.post()
    
    Returns:
        requests.Response object
    
    Raises:
        EgressGuardError: If URL is not allowlisted
        ImportError: If requests library is not available
    """
    if not REQUESTS_AVAILABLE:
        raise ImportError("requests library is required for http_post()")
    
    # Validate URL against egress allowlist
    validated_url, resolved_ip = validate_outbound_url(url, calling_module=calling_module)
    
    # Generate correlation ID for logging
    correlation_id = str(uuid.uuid4())[:8]
    
    # Prepare headers
    request_headers = headers or {}
    if json and "Content-Type" not in request_headers:
        request_headers["Content-Type"] = "application/json"
    
    try:
        # Make the request
        if json:
            response = requests.post(
                validated_url,
                json=json,
                timeout=timeout,
                headers=request_headers,
                **kwargs
            )
        else:
            response = requests.post(
                validated_url,
                data=data,
                timeout=timeout,
                headers=request_headers,
                **kwargs
            )
        
        # Log the request for security audit
        log_outbound_request(
            validated_url,
            method="POST",
            status_code=response.status_code,
            calling_module=calling_module,
            correlation_id=correlation_id
        )
        
        return response
    
    except requests.exceptions.RequestException as e:
        # Log failed requests
        logger.error(
            f"[HTTP_CLIENT] POST request failed: {url} (called from {calling_module}): {e}"
        )
        raise
    except Exception as e:
        logger.error(
            f"[HTTP_CLIENT] Unexpected error in http_post: {url} (called from {calling_module}): {e}"
        )
        raise


async def async_http_get(
    url: str,
    timeout: float = 10.0,
    headers: Optional[Dict[str, str]] = None,
    calling_module: str = "unknown",
    **kwargs
) -> Tuple[Optional[int], Optional[Any]]:
    """
    Asynchronous HTTP GET request with egress guard validation.
    Returns (status_code, json_data) tuple compatible with data_sources.py usage.
    
    Args:
        url: The URL to request (must be allowlisted)
        timeout: Request timeout in seconds
        headers: Optional HTTP headers
        calling_module: Name of the calling module (for logging)
        **kwargs: Additional arguments passed to aiohttp/httpx client
    
    Returns:
        Tuple of (status_code, json_data) or (None, None) on error
    
    Raises:
        EgressGuardError: If URL is not allowlisted
        ImportError: If aiohttp/httpx is not available
    """
    # Validate URL against egress allowlist
    validated_url, resolved_ip = validate_outbound_url(url, calling_module=calling_module)
    
    # Generate correlation ID for logging
    correlation_id = str(uuid.uuid4())[:8]
    
    # Prepare headers
    request_headers = headers or {}
    
    # Try aiohttp first, then httpx
    if AIOHTTP_AVAILABLE:
        try:
            from aiohttp import ClientTimeout
            timeout_obj = ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                async with session.get(validated_url, headers=request_headers, **kwargs) as response:
                    status_code = response.status
                    try:
                        data = await response.json()
                    except Exception:
                        data = None
                    
                    # Log the request for security audit
                    log_outbound_request(
                        validated_url,
                        method="GET",
                        status_code=status_code,
                        calling_module=calling_module,
                        correlation_id=correlation_id
                    )
                    
                    return status_code, data
        except Exception as e:
            logger.error(f"[HTTP_CLIENT] aiohttp GET failed: {url}: {e}")
            return None, None
    
    # Fallback to httpx if available
    try:
        import httpx
        timeout_obj = httpx.Timeout(timeout)
        async with httpx.AsyncClient(timeout=timeout_obj) as client:
            response = await client.get(validated_url, headers=request_headers, **kwargs)
            status_code = response.status_code
            
            # Log the request for security audit
            log_outbound_request(
                validated_url,
                method="GET",
                status_code=status_code,
                calling_module=calling_module,
                correlation_id=correlation_id
            )
            
            return status_code, response.json()
    except ImportError:
        logger.error("[HTTP_CLIENT] Neither aiohttp nor httpx is available for async requests")
        return None, None
    except Exception as e:
        logger.error(f"[HTTP_CLIENT] httpx GET failed: {url}: {e}")
        return None, None

