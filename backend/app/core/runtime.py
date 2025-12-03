"""
Runtime origin detection and guards

This module provides utilities to determine whether code is running in:
- AWS (production): Real orders and official Telegram alerts
- LOCAL (development): No real orders, no production Telegram alerts

Usage:
    from app.core.runtime import is_aws_runtime, is_local_runtime
    
    if is_aws_runtime():
        # Production logic
        pass
    else:
        # Development/debug logic
        pass
"""
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)


def get_runtime_origin() -> str:
    """
    Get the current runtime origin.
    
    Returns:
        "AWS" if RUNTIME_ORIGIN=aws (production)
        "LOCAL" otherwise (development)
    
    Configuration:
        - Set RUNTIME_ORIGIN=aws on AWS deployment (in docker-compose or env)
        - Defaults to "LOCAL" for safety (prevents accidental production actions)
    """
    runtime_origin = (settings.RUNTIME_ORIGIN or "").strip().upper()
    
    if runtime_origin == "AWS":
        return "AWS"
    else:
        if runtime_origin and runtime_origin != "LOCAL":
            logger.warning(
                f"Unknown RUNTIME_ORIGIN value '{runtime_origin}', defaulting to LOCAL. "
                f"Valid values are: 'AWS' or 'LOCAL'"
            )
        return "LOCAL"


def is_aws_runtime() -> bool:
    """
    Check if code is running in AWS (production) environment.
    
    Returns:
        True if RUNTIME_ORIGIN=aws, False otherwise
    """
    return get_runtime_origin() == "AWS"


def is_local_runtime() -> bool:
    """
    Check if code is running in LOCAL (development) environment.
    
    Returns:
        True if RUNTIME_ORIGIN is not "AWS", False otherwise
    """
    return not is_aws_runtime()


