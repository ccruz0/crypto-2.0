from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
import os
import logging
import socket
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

# Determine database URL
# Priority: 1) DATABASE_URL env var, 2) settings.DATABASE_URL, 3) SQLite fallback
database_url = os.getenv("DATABASE_URL", settings.DATABASE_URL)

# If no DATABASE_URL is explicitly set or it's the default PostgreSQL (which may not be available),
# check if we should use SQLite as fallback for local development
use_sqlite_fallback = False

if not database_url:
    use_sqlite_fallback = True
elif database_url.startswith("postgresql://"):
    # PostgreSQL is configured - use it (this is what Docker Compose provides)
    use_sqlite_fallback = False

    # Guard: when running outside Docker, host "db" is not resolvable. Fallback to localhost automatically.
    parsed = urlparse(database_url)
    if parsed.hostname == "db":
        try:
            socket.gethostbyname(parsed.hostname)
        except socket.gaierror:
            logger.warning("DATABASE_URL host 'db' not resolvable. Falling back to localhost for local execution.")
            # Rebuild URL with localhost while keeping credentials/port
            netloc = parsed.netloc.replace("db", "localhost", 1)
            parsed = parsed._replace(netloc=netloc)
            database_url = urlunparse(parsed)

    logger.info(f"Using PostgreSQL database: {database_url.split('@')[-1] if '@' in database_url else database_url}")
else:
    use_sqlite_fallback = False

# Only fallback to SQLite if explicitly needed (no DB configured and local env)
if use_sqlite_fallback and os.getenv("ENVIRONMENT", "local") == "local":
    database_url = "sqlite:///./backend.db"
    logger.info("Using SQLite fallback database: backend.db")

# Configure engine with appropriate settings
if database_url.startswith("sqlite"):
    # SQLite configuration
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},  # Required for SQLite with FastAPI
        pool_pre_ping=True,
        echo=False
    )
    logger.info("Database engine configured for SQLite")
else:
    # PostgreSQL configuration with increased connection pool and timeout
    # Add connect_args with connect_timeout to prevent hanging
    # Use lazy connection - don't connect until first query
    try:
        engine = create_engine(
            database_url,
            pool_size=5,          # Reduced pool size to avoid connection issues
            max_overflow=10,       # Reduced overflow
            pool_timeout=3,       # Faster timeout
            pool_recycle=3600,     # Recycle connections every hour
            pool_pre_ping=True,    # Verify connections before use
            connect_args={
                "connect_timeout": 3,  # Connection timeout in seconds (reduced)
            },
            # Don't connect on engine creation - lazy connection
            poolclass=None  # Use default pool
        )
        logger.info("Database engine configured for PostgreSQL with timeouts (lazy connection)")
    except Exception as engine_err:
        logger.error(f"Failed to create database engine: {engine_err}", exc_info=True)
        # Create a dummy engine that will fail gracefully
        engine = None

# Create SessionLocal only if engine exists
if engine:
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
else:
    # Create a dummy sessionmaker that won't block
    SessionLocal = None
    logger.warning("SessionLocal is None - database not available")

Base = declarative_base()

def get_db():
    """Dependency for getting database session - non-blocking with graceful fallback"""
    if SessionLocal is None:
        # Database not available - return None and let endpoints handle it
        yield None
        return
    
    db = None
    try:
        # Create session without blocking test
        db = SessionLocal()
        yield db
    except Exception as e:
        logger.error(f"Database session error: {e}", exc_info=True)
        if db:
            try:
                db.rollback()
            except:
                pass
        # Re-raise the exception instead of yielding None (which causes generator error)
        raise
    finally:
        if db:
            try:
                db.close()
            except Exception as close_err:
                logger.warning(f"Error closing database session: {close_err}")

