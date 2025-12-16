from sqlalchemy import create_engine, text, inspect
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
    # CRITICAL: Only fallback to localhost if we're NOT in a Docker/container environment
    # Check if we're in Docker by looking for /.dockerenv or checking if we're in a container
    parsed = urlparse(database_url)
    if parsed.hostname == "db":
        is_docker = os.path.exists("/.dockerenv") or os.environ.get("container") is not None
        try:
            socket.gethostbyname(parsed.hostname)
            # Hostname resolves - keep using "db" (correct for Docker environments)
            logger.debug(f"Database hostname 'db' resolved successfully (Docker: {is_docker})")
        except socket.gaierror:
            if not is_docker:
                # Only fallback to localhost if we're NOT in Docker
                logger.warning("DATABASE_URL host 'db' not resolvable. Falling back to localhost for local execution.")
                # Rebuild URL with localhost while keeping credentials/port
                netloc = parsed.netloc.replace("db", "localhost", 1)
                parsed = parsed._replace(netloc=netloc)
                database_url = urlunparse(parsed)
            else:
                # In Docker but "db" not resolvable - this is a real problem
                logger.error("DATABASE_URL host 'db' not resolvable in Docker environment. Check Docker network configuration.")
                # Don't change the URL - let it fail with a clear error

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
            pool_size=10,          # Increased pool size for better concurrency
            max_overflow=20,       # Increased overflow to handle spikes
            pool_timeout=30,       # Longer timeout to wait for connections from pool
            pool_recycle=3600,     # Recycle connections every hour
            pool_pre_ping=True,    # Verify connections before use (critical for reliability)
            connect_args={
                "connect_timeout": 10,  # Connection timeout in seconds (increased for stability)
                "keepalives": 1,        # Enable TCP keepalives
                "keepalives_idle": 30,  # Start keepalives after 30s of idle
                "keepalives_interval": 10,  # Send keepalives every 10s
                "keepalives_count": 3,  # Drop connection after 3 failed keepalives
            },
            # Don't connect on engine creation - lazy connection
            poolclass=None  # Use default pool
        )
        logger.info("Database engine configured for PostgreSQL with improved pool settings (lazy connection)")
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


def test_database_connection() -> tuple[bool, str]:
    """
    Test database connection and return (success, message).
    Useful for diagnostics and health checks.
    """
    if engine is None:
        return False, "Database engine is not configured"
    
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "Database connection successful"
    except Exception as e:
        error_msg = str(e)
        if "could not translate host name" in error_msg.lower():
            parsed = urlparse(database_url)
            hostname = parsed.hostname
            return False, f"Database hostname '{hostname}' cannot be resolved. Ensure the database container is running and on the same Docker network."
        elif "connection refused" in error_msg.lower() or "connection timed out" in error_msg.lower():
            return False, f"Database connection refused or timed out. Check if the database is running and accessible."
        else:
            return False, f"Database connection failed: {error_msg}"


def table_has_column(db_engine, table_name: str, column_name: str) -> bool:
    """Return True if the given table contains the specified column."""
    if db_engine is None or not table_name or not column_name:
        return False
    try:
        inspector = inspect(db_engine)
        columns = inspector.get_columns(table_name)
        return any(col.get("name") == column_name for col in columns)
    except Exception as inspect_err:
        logger.warning(
            "Unable to inspect table %s for column %s: %s",
            table_name,
            column_name,
            inspect_err,
        )
        return False


def ensure_optional_columns(db_engine=None):
    """
    Ensure optional columns exist in critical tables.
    This guards against environments that haven't run the latest migrations.
    """
    engine_to_use = db_engine or engine
    if engine_to_use is None:
        logger.warning("Cannot ensure optional columns - engine is None")
        return
    
    try:
        from app.models.watchlist import WatchlistItem
        from app.models.telegram_message import TelegramMessage
    except Exception as import_err:
        logger.warning(f"Cannot load models to verify optional columns: {import_err}")
        return
    
    table_configs = {}
    
    watchlist_table = getattr(getattr(WatchlistItem, "__table__", None), "name", None) or getattr(
        WatchlistItem, "__tablename__", "watchlist_items"
    )
    table_configs[watchlist_table] = [
        ("is_deleted", "BOOLEAN NOT NULL DEFAULT 0"),
        ("min_price_change_pct", "DOUBLE PRECISION"),
    ]
    
    telegram_table = getattr(getattr(TelegramMessage, "__table__", None), "name", None) or getattr(
        TelegramMessage, "__tablename__", "telegram_messages"
    )
    table_configs[telegram_table] = [
        ("throttle_status", "VARCHAR(20)"),
        ("throttle_reason", "TEXT"),
    ]
    
    try:
        with engine_to_use.begin() as conn:
            for table_name, optional_columns in table_configs.items():
                for column_name, column_sql in optional_columns:
                    if table_has_column(engine_to_use, table_name, column_name):
                        continue
                    stmt = text(
                        f"ALTER TABLE {table_name} "
                        f"ADD COLUMN IF NOT EXISTS {column_name} {column_sql}"
                    )
                    conn.execute(stmt)
                    logger.info("Added optional column %s.%s", table_name, column_name)
    except Exception as ensure_err:
        logger.warning(f"Could not ensure optional columns: {ensure_err}", exc_info=True)

def get_db():
    """Dependency for getting database session - non-blocking with graceful fallback
    
    CRITICAL: This function ensures database sessions are properly closed even if:
    - The handler raises an exception
    - The handler doesn't explicitly commit/rollback
    """
    if SessionLocal is None:
        # Database not available - return None and let endpoints handle it
        yield None
        return
    
    db = None
    try:
        # Create session without blocking test
        db = SessionLocal()
        yield db
        # Note: If handler completed successfully, it should have explicitly committed
        # If not, db.close() in finally will rollback any uncommitted transactions
    except Exception as e:
        error_msg = str(e)
        # Check if it's a hostname resolution error
        if "could not translate host name" in error_msg.lower() or "temporary failure in name resolution" in error_msg.lower():
            logger.error(f"Database hostname resolution error: {e}")
            logger.error("This usually means the database container is not running or not on the same Docker network.")
            logger.error(f"Current DATABASE_URL hostname: {urlparse(database_url).hostname if 'database_url' in globals() else 'unknown'}")
            # Try to provide helpful error message
            if "db" in error_msg.lower():
                logger.error("The hostname 'db' is not resolvable. If running outside Docker, ensure DATABASE_URL uses 'localhost' instead.")
        else:
            logger.error(f"Database session error: {e}", exc_info=True)
        
        if db:
            try:
                # CRITICAL: Rollback on exception to release transaction locks
                db.rollback()
            except Exception as rollback_err:
                logger.warning(f"Error rolling back database session: {rollback_err}")
        # Re-raise the exception instead of yielding None (which causes generator error)
        raise
    finally:
        # CRITICAL: Always close the session to release the connection back to the pool
        # This will automatically rollback any uncommitted transactions
        if db:
            try:
                db.close()
            except Exception as close_err:
                logger.warning(f"Error closing database session: {close_err}")
