"""
Environment detection and configuration for the backend
"""

import os
from typing import Literal
from pydantic_settings import BaseSettings


class EnvironmentSettings(BaseSettings):
    """Environment-specific settings"""
    
    ENVIRONMENT: Literal["local", "aws"] = "local"
    api_base_url: str = "http://localhost:8002"
    frontend_url: str = "http://localhost:3000"
    database_url: str = "postgresql://trader:traderpass@db:5432/atp"
    
    # AWS-specific settings
    aws_region: str = "ap-southeast-1"
    # aws_instance_ip: Removed hardcoded IP - use PUBLIC_BASE_URL or API_BASE_URL env vars instead
    
    # Failover settings
    failover_enabled: bool = True
    health_check_interval: int = 5000
    
    class Config:
        env_file = [".env", ".env.local", ".env.aws"]
        case_sensitive = False
        extra = "ignore"  # Ignore extra environment variables


def get_environment() -> str:
    """Detect the current environment"""
    return os.getenv("ENVIRONMENT", "local")


def getRuntimeEnv() -> Literal["local", "aws"]:
    """
    Get normalized runtime environment.
    
    Returns:
        "local" or "aws" (normalized, lowercase)
    
    This is the authoritative function for environment detection.
    Uses ENVIRONMENT env var, normalizes to "local" or "aws".
    """
    env = (os.getenv("ENVIRONMENT") or "local").strip().lower()
    if env == "aws":
        return "aws"
    else:
        return "local"  # Default to local for safety


def is_local() -> bool:
    """Check if running in local environment"""
    return get_environment() == "local"


def is_aws() -> bool:
    """Check if running in AWS environment"""
    return get_environment() == "aws"


def _normalize_cors_origin(origin: str) -> str:
    """Normalize CORS origin to scheme://host:port format (no path, query, or fragment)"""
    origin = origin.strip()
    if not origin:
        return ""
    # Remove path, query, and fragment
    if "://" in origin:
        scheme, rest = origin.split("://", 1)
        # Extract host:port (everything before first /, ?, or #)
        host_port = rest.split("/")[0].split("?")[0].split("#")[0]
        return f"{scheme}://{host_port}"
    return origin


def get_cors_origins() -> list[str]:
    """Get CORS origins based on environment
    
    Returns list of normalized origins (scheme://host:port, no paths/query/fragment).
    Duplicates are removed.
    """
    # Allow external access when ENABLE_EXTERNAL_ACCESS is set
    enable_external = os.getenv("ENABLE_EXTERNAL_ACCESS", "false").lower() == "true"
    
    if enable_external:
        # Allow all origins when external access is enabled (for tunneling/port forwarding)
        return ["*"]
    elif is_local():
        return [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            # Allow local network access
            "http://172.20.10.2:3000",
            "http://0.0.0.0:3000",
        ]
    elif is_aws():
        origins = [
            # Primary domain (preferred)
            "https://dashboard.hilovivo.com",
            "https://www.dashboard.hilovivo.com",
            "https://hilovivo.com",
            "https://www.hilovivo.com",
        ]
        # Add FRONTEND_URL if set (normalize to remove paths)
        frontend_url = os.getenv("FRONTEND_URL", "")
        if frontend_url:
            normalized = _normalize_cors_origin(frontend_url)
            if normalized:
                origins.append(normalized)
                # Also add HTTP version if HTTPS was provided
                if normalized.startswith("https://"):
                    origins.append(normalized.replace("https://", "http://"))
        
        # Add PUBLIC_BASE_URL if set (normalize to remove paths)
        public_base = os.getenv("PUBLIC_BASE_URL", "")
        if public_base:
            normalized = _normalize_cors_origin(public_base)
            if normalized:
                origins.append(normalized)
                # Also add HTTP version if HTTPS was provided
                if normalized.startswith("https://"):
                    origins.append(normalized.replace("https://", "http://"))
        
        # Add custom CORS origins from environment if set
        custom_origins = os.getenv("CORS_ORIGINS", "")
        if custom_origins:
            for origin in custom_origins.split(","):
                normalized = _normalize_cors_origin(origin)
                if normalized:
                    origins.append(normalized)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_origins = []
        for origin in origins:
            if origin not in seen:
                seen.add(origin)
                unique_origins.append(origin)
        
        return unique_origins
    else:
        return ["*"]


def get_api_base_url() -> str:
    """Get the API base URL based on environment
    
    Priority:
    1. API_BASE_URL env var (explicit override)
    2. PUBLIC_BASE_URL env var (base URL, appends /api if needed)
    3. Local dev fallback: http://localhost:8002
    """
    # Explicit API_BASE_URL takes precedence
    api_url = os.getenv("API_BASE_URL")
    if api_url:
        # Normalize: remove trailing slash to avoid double slashes
        return api_url.rstrip('/')
    
    # Try PUBLIC_BASE_URL (preferred for AWS deployments)
    public_base = os.getenv("PUBLIC_BASE_URL")
    if public_base:
        # Normalize: remove trailing slash
        public_base = public_base.rstrip('/')
        # If it already ends with /api, use as-is; otherwise append /api
        if public_base.endswith('/api'):
            return public_base
        return f"{public_base}/api"
    
    # Local dev fallback only
    if is_local():
        return "http://localhost:8002"
    
    # AWS without env vars: use domain (preferred) or fail
    # This ensures deployments must set env vars explicitly
    return os.getenv("API_BASE_URL", "https://dashboard.hilovivo.com/api")


def get_frontend_url() -> str:
    """Get the frontend URL based on environment
    
    Priority:
    1. FRONTEND_URL env var (explicit override)
    2. PUBLIC_BASE_URL env var (base URL, use as-is for frontend)
    3. Local dev fallback: http://localhost:3000
    """
    # Explicit FRONTEND_URL takes precedence
    frontend_url = os.getenv("FRONTEND_URL")
    if frontend_url:
        # Normalize: remove trailing slash to avoid double slashes
        return frontend_url.rstrip('/')
    
    # Try PUBLIC_BASE_URL (preferred for AWS deployments)
    public_base = os.getenv("PUBLIC_BASE_URL")
    if public_base:
        # Normalize: remove trailing slash
        return public_base.rstrip('/')
    
    # Local dev fallback only
    if is_local():
        return "http://localhost:3000"
    
    # AWS without env vars: use domain (preferred) or fail
    # This ensures deployments must set env vars explicitly
    return os.getenv("FRONTEND_URL", "https://dashboard.hilovivo.com")


# Global settings instance
settings = EnvironmentSettings()
