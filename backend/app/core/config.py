from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    PROJECT_NAME: str = "Automated Trading Platform"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = "postgresql://trader:traderpass@db:5432/atp"
    
    # Security
    # SECRET_KEY: Must be set via environment variable for security
    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    SECRET_KEY: Optional[str] = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Environment
    ENVIRONMENT: str = "local"
    # APP_ENV: Explicit environment identifier for alert routing ("aws" or "local")
    # Used to route alerts to different Telegram channels and prefix messages
    # Set APP_ENV=aws on AWS deployment, APP_ENV=local for local development
    APP_ENV: Optional[str] = None
    # RUN_TELEGRAM: Control whether Telegram messages are sent
    # Set RUN_TELEGRAM=true on AWS (where all Telegram messages must be sent)
    # Set RUN_TELEGRAM=false for local development (must never send Telegram messages)
    RUN_TELEGRAM: Optional[str] = None
    # RUNTIME_ORIGIN: Explicit runtime origin identifier ("AWS" or "LOCAL")
    # Used to enforce guards on order placement and Telegram alerts
    # Set RUNTIME_ORIGIN=AWS on AWS deployment (production)
    # Defaults to "LOCAL" for safety (prevents accidental production actions)
    RUNTIME_ORIGIN: str = "LOCAL"
    
    # Trading APIs
    BINANCE_API_KEY: Optional[str] = None
    BINANCE_SECRET_KEY: Optional[str] = None
    ALPACA_API_KEY: Optional[str] = None
    ALPACA_SECRET_KEY: Optional[str] = None
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    
    # Proxy settings
    USE_CRYPTO_PROXY: Optional[str] = None
    CRYPTO_PROXY_URL: Optional[str] = None
    CRYPTO_PROXY_TOKEN: Optional[str] = None
    LIVE_TRADING: Optional[str] = None

    # Telegram
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None  # Deprecated: use TELEGRAM_CHAT_ID_AWS or TELEGRAM_CHAT_ID_LOCAL
    TELEGRAM_CHAT_ID_AWS: Optional[str] = None  # AWS production channel
    TELEGRAM_CHAT_ID_LOCAL: Optional[str] = None  # Local development channel (not used for sending)
    
    class Config:
        env_file = ".env"
        extra = "ignore"  # Ignore extra environment variables

settings = Settings()

# Validate SECRET_KEY is set (critical for security)
if not settings.SECRET_KEY or settings.SECRET_KEY == "your-secret-key-here":
    import warnings
    import os
    # Check if we're in a test environment
    if os.getenv("ENVIRONMENT") != "test" and os.getenv("APP_ENV") != "test":
        warnings.warn(
            "SECRET_KEY is not set or using default value. "
            "This is a security risk. Set SECRET_KEY in your environment variables. "
            "Generate with: python -c 'import secrets; print(secrets.token_urlsafe(32))'",
            UserWarning
        )
