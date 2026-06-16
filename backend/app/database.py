from sqlalchemy import create_engine, text, inspect
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker
from app.core.config import settings
from app.core.environment import is_local
import os
import sys
import logging
import socket
from typing import Sequence
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
if use_sqlite_fallback and is_local():
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


def _aws_startup_db_connectivity_check() -> None:
    """
    Production AWS backend: fail fast if DATABASE_URL cannot reach Postgres (no retries).
    Uses a short TCP connect timeout and a single SELECT 1; does not use the main pool.
    """
    if engine is None or not database_url.startswith("postgresql://"):
        return
    if settings.ENVIRONMENT != "aws" or settings.RUNTIME_ORIGIN != "AWS":
        return
    if os.getenv("ENVIRONMENT") in ("test",) or os.getenv("APP_ENV") in ("test",):
        return
    ping_engine = create_engine(
        database_url,
        poolclass=NullPool,
        connect_args={
            "connect_timeout": 3,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
        },
    )
    try:
        with ping_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("DB connectivity check passed")
    except Exception as e:
        logger.error("DB connectivity check failed")
        raise RuntimeError(
            "Cannot connect to PostgreSQL at startup (AWS runtime). "
            "Verify DATABASE_URL, network to host 'db', and Postgres health."
        ) from e
    finally:
        ping_engine.dispose()


_aws_startup_db_connectivity_check()


def create_db_session() -> Session:
    """
    Open a new SQLAlchemy session for scripts, CLIs, and one-off jobs.

    Raises:
        RuntimeError: If ``SessionLocal`` is None (engine creation failed or DB URL missing).
            Prefer this over bare ``SessionLocal()`` in scripts so failures are explicit.

    Note:
        FastAPI routes should keep using ``get_db()``, which yields ``None`` when the DB is
        unavailable so handlers can degrade gracefully.
    """
    if SessionLocal is None:
        raise RuntimeError(
            "Database is not configured: SessionLocal is None (engine missing or failed to "
            "initialize). Set DATABASE_URL or use the local SQLite fallback. "
            "Use app.database.create_db_session() in scripts instead of calling SessionLocal() "
            "directly. See docs/development/ATP_NOTIFIER_AND_DB_PATTERNS.md."
        )
    return SessionLocal()


def exit_2_if_missing_schema_tables(
    exc: OperationalError,
    *,
    table_names: Sequence[str],
    stderr_message: str,
) -> None:
    """
    For scripts/CLIs: if ``exc`` looks like a missing-table failure, print ``stderr_message`` to
    stderr and ``sys.exit(2)``. Otherwise re-raise ``exc``.

    Matches the common SQLite message (``no such table``) or any of ``table_names`` appearing in
    the error text (covers PostgreSQL ``relation \"...\" does not exist`` when the name is present).
    """
    err_lower = str(exc).lower()
    names_lower = [n.lower() for n in table_names]
    if "no such table" not in err_lower and not any(n in err_lower for n in names_lower):
        raise exc
    print(stderr_message, file=sys.stderr)
    sys.exit(2)


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


def table_exists(db_engine, table_name: str) -> bool:
    """Return True if the given table exists."""
    if db_engine is None or not table_name:
        return False
    try:
        inspector = inspect(db_engine)
        return table_name in inspector.get_table_names()
    except Exception as inspect_err:
        logger.warning(
            "Unable to check if table %s exists: %s",
            table_name,
            inspect_err,
        )
        return False


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


def ensure_telegram_update_dedup_table(engine_to_use) -> bool:
    """
    Create telegram_update_dedup (+ index on created_at) if missing. Idempotent DDL.
    Migrates legacy tables that used received_at: adds created_at and backfills when needed.

    Returns True if the table exists after this call, False if engine is None or DDL failed.
    """
    if engine_to_use is None:
        logger.warning("ensure_telegram_update_dedup_table: engine is None")
        return False
    tname = "telegram_update_dedup"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Telegram poller)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            """
                            CREATE TABLE IF NOT EXISTS telegram_update_dedup (
                                update_id BIGINT PRIMARY KEY,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            """
                            CREATE TABLE IF NOT EXISTS telegram_update_dedup (
                                update_id BIGINT PRIMARY KEY,
                                created_at TIMESTAMP DEFAULT NOW()
                            )
                            """
                        )
                    )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_telegram_update_dedup_created_at "
                        "ON telegram_update_dedup (created_at)"
                    )
                )
            logger.info("[BOOT] Created table telegram_update_dedup")
        else:
            # Legacy: received_at-only schema → add created_at for consistent queries
            if not table_has_column(engine_to_use, tname, "created_at"):
                has_received = table_has_column(engine_to_use, tname, "received_at")
                with engine_to_use.begin() as conn:
                    if engine_to_use.dialect.name == "sqlite":
                        conn.execute(
                            text(
                                "ALTER TABLE telegram_update_dedup ADD COLUMN created_at TIMESTAMP "
                                "DEFAULT CURRENT_TIMESTAMP"
                            )
                        )
                        if has_received:
                            conn.execute(
                                text(
                                    "UPDATE telegram_update_dedup SET created_at = received_at "
                                    "WHERE created_at IS NULL"
                                )
                            )
                    else:
                        conn.execute(
                            text(
                                "ALTER TABLE telegram_update_dedup ADD COLUMN IF NOT EXISTS "
                                "created_at TIMESTAMP DEFAULT NOW()"
                            )
                        )
                        if has_received:
                            conn.execute(
                                text(
                                    "UPDATE telegram_update_dedup SET created_at = received_at "
                                    "WHERE created_at IS NULL"
                                )
                            )
            with engine_to_use.begin() as conn:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_telegram_update_dedup_created_at "
                        "ON telegram_update_dedup (created_at)"
                    )
                )
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_telegram_update_dedup_table failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_marketing_intake_table(engine_to_use) -> bool:
    """
    Persist Telegram marketing intake metadata (no secret values) across gunicorn worker restarts.

    Returns True if the table exists after this call.
    """
    if engine_to_use is None:
        logger.warning("ensure_jarvis_marketing_intake_table: engine is None")
        return False
    tname = "jarvis_marketing_intake_state"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Jarvis marketing intake)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                chat_id VARCHAR(128) NOT NULL,
                                user_id VARCHAR(128) NOT NULL,
                                payload TEXT NOT NULL,
                                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                PRIMARY KEY (chat_id, user_id)
                            )
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                chat_id VARCHAR(128) NOT NULL,
                                user_id VARCHAR(128) NOT NULL,
                                payload TEXT NOT NULL,
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                PRIMARY KEY (chat_id, user_id)
                            )
                            """
                        )
                    )
            logger.info("[BOOT] Created table %s", tname)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_marketing_intake_table failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_task_runs_table(engine_to_use) -> bool:
    """
    Persist Jarvis LangGraph MVP task run history.

    Returns True if the table exists after this call.
    """
    if engine_to_use is None:
        logger.warning("ensure_jarvis_task_runs_table: engine is None")
        return False
    tname = "jarvis_task_runs"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Jarvis task runs)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                task_id TEXT NOT NULL UNIQUE,
                                task TEXT NOT NULL,
                                status TEXT NOT NULL,
                                risk_level TEXT NOT NULL,
                                dry_run BOOLEAN NOT NULL,
                                plan_json TEXT,
                                tool_results_json TEXT,
                                review_json TEXT,
                                estimated_cost_usd REAL,
                                actual_cost_usd REAL DEFAULT 0,
                                objective TEXT DEFAULT '',
                                priority TEXT DEFAULT 'normal',
                                artifacts_json TEXT,
                                approval_required BOOLEAN DEFAULT 0,
                                approval_status TEXT DEFAULT 'not_required',
                                current_step TEXT,
                                started_at TIMESTAMP,
                                final_answer TEXT,
                                error TEXT,
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                completed_at TIMESTAMP
                            )
                            """
                        )
                    )
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_jarvis_task_runs_status ON {tname} (status)"))
                    conn.execute(
                        text(f"CREATE INDEX IF NOT EXISTS ix_jarvis_task_runs_created_at ON {tname} (created_at DESC)")
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                task_id TEXT NOT NULL UNIQUE,
                                task TEXT NOT NULL,
                                status TEXT NOT NULL,
                                risk_level TEXT NOT NULL,
                                dry_run BOOLEAN NOT NULL,
                                plan_json JSONB,
                                tool_results_json JSONB,
                                review_json JSONB,
                                estimated_cost_usd NUMERIC,
                                actual_cost_usd NUMERIC DEFAULT 0,
                                objective TEXT DEFAULT '',
                                priority TEXT DEFAULT 'normal',
                                artifacts_json JSONB,
                                approval_required BOOLEAN DEFAULT FALSE,
                                approval_status TEXT DEFAULT 'not_required',
                                current_step TEXT,
                                started_at TIMESTAMPTZ,
                                final_answer TEXT,
                                error TEXT,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                completed_at TIMESTAMPTZ
                            )
                            """
                        )
                    )
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_jarvis_task_runs_status ON {tname} (status)"))
                    conn.execute(
                        text(f"CREATE INDEX IF NOT EXISTS ix_jarvis_task_runs_created_at ON {tname} (created_at DESC)")
                    )
            logger.info("[BOOT] Created table %s", tname)
        if table_exists(engine_to_use, tname):
            _ensure_jarvis_task_runs_phase3_columns(engine_to_use)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_task_runs_table failed: %s", e, exc_info=True)
        return False


def _ensure_jarvis_task_runs_phase3_columns(engine_to_use) -> bool:
    """Add Phase 3 task execution columns to jarvis_task_runs if missing."""
    if engine_to_use is None or not table_exists(engine_to_use, "jarvis_task_runs"):
        return False
    try:
        inspector = inspect(engine_to_use)
        columns = {col["name"] for col in inspector.get_columns("jarvis_task_runs")}
        is_sqlite = engine_to_use.dialect.name == "sqlite"
        additions: list[tuple[str, str]] = []
        spec = [
            ("objective", "TEXT DEFAULT ''"),
            ("priority", "TEXT DEFAULT 'normal'"),
            ("artifacts_json", "TEXT" if is_sqlite else "JSONB"),
            ("approval_required", "BOOLEAN DEFAULT 0" if is_sqlite else "BOOLEAN DEFAULT FALSE"),
            ("approval_status", "TEXT DEFAULT 'not_required'"),
            ("actual_cost_usd", "REAL DEFAULT 0" if is_sqlite else "NUMERIC DEFAULT 0"),
            ("current_step", "TEXT"),
            ("started_at", "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"),
        ]
        for col_name, col_def in spec:
            if col_name not in columns:
                additions.append((col_name, col_def))
        if not additions:
            return True
        with engine_to_use.begin() as conn:
            for col_name, col_def in additions:
                conn.execute(text(f"ALTER TABLE jarvis_task_runs ADD COLUMN {col_name} {col_def}"))
        logger.info("[BOOT] Added jarvis_task_runs Phase 3 columns: %s", [a[0] for a in additions])
        return True
    except Exception as e:
        logger.warning("_ensure_jarvis_task_runs_phase3_columns failed: %s", e)
        return False


def ensure_jarvis_execution_log_table(engine_to_use) -> bool:
    """Persist Jarvis Phase 3 execution audit log."""
    if engine_to_use is None:
        return False
    tname = "jarvis_execution_log"
    try:
        if not table_exists(engine_to_use, tname):
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                log_id TEXT NOT NULL UNIQUE,
                                task_id TEXT NOT NULL,
                                agent TEXT NOT NULL,
                                tool TEXT NOT NULL,
                                input_summary TEXT,
                                output_summary TEXT,
                                duration_ms INTEGER DEFAULT 0,
                                metadata_json TEXT,
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            )
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                log_id TEXT NOT NULL UNIQUE,
                                task_id TEXT NOT NULL,
                                agent TEXT NOT NULL,
                                tool TEXT NOT NULL,
                                input_summary TEXT,
                                output_summary TEXT,
                                duration_ms INTEGER DEFAULT 0,
                                metadata_json JSONB,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                    )
                conn.execute(
                    text(f"CREATE INDEX IF NOT EXISTS ix_jarvis_execution_log_task_id ON {tname} (task_id)")
                )
            logger.info("[BOOT] Created table %s", tname)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_execution_log_table failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_task_approvals_table(engine_to_use) -> bool:
    """Persist Jarvis Phase 3 task approval history."""
    if engine_to_use is None:
        return False
    tname = "jarvis_task_approvals"
    try:
        if not table_exists(engine_to_use, tname):
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                approval_id TEXT NOT NULL UNIQUE,
                                task_id TEXT NOT NULL,
                                decision TEXT NOT NULL,
                                actor_id TEXT NOT NULL,
                                comment TEXT,
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            )
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                approval_id TEXT NOT NULL UNIQUE,
                                task_id TEXT NOT NULL,
                                decision TEXT NOT NULL,
                                actor_id TEXT NOT NULL,
                                comment TEXT,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                    )
                conn.execute(
                    text(f"CREATE INDEX IF NOT EXISTS ix_jarvis_task_approvals_task_id ON {tname} (task_id)")
                )
            logger.info("[BOOT] Created table %s", tname)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_task_approvals_table failed: %s", e, exc_info=True)
        return False


def _ensure_jarvis_investigations_phase4b_columns(engine_to_use) -> bool:
    """Add Phase 4B proposal linkage columns to jarvis_investigations if missing."""
    if engine_to_use is None or not table_exists(engine_to_use, "jarvis_investigations"):
        return False
    try:
        additions: list[tuple[str, str]] = []
        for col_name in ("proposal_task_id", "proposal_status"):
            if not table_has_column(engine_to_use, "jarvis_investigations", col_name):
                additions.append((col_name, "TEXT"))
        if not additions:
            return True
        with engine_to_use.begin() as conn:
            for col_name, col_def in additions:
                if engine_to_use.dialect.name == "postgresql":
                    conn.execute(
                        text(
                            f"ALTER TABLE jarvis_investigations "
                            f"ADD COLUMN IF NOT EXISTS {col_name} {col_def}"
                        )
                    )
                else:
                    conn.execute(
                        text(f"ALTER TABLE jarvis_investigations ADD COLUMN {col_name} {col_def}")
                    )
        logger.info(
            "[BOOT] Added jarvis_investigations Phase 4B columns: %s",
            [a[0] for a in additions],
        )
        return True
    except Exception as e:
        logger.warning("_ensure_jarvis_investigations_phase4b_columns failed: %s", e)
        return False


def ensure_jarvis_investigations_table(engine_to_use) -> bool:
    """Persist Jarvis Phase 4A production diagnostic investigation reports."""
    if engine_to_use is None:
        logger.warning("ensure_jarvis_investigations_table: engine is None")
        return False
    tname = "jarvis_investigations"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Jarvis investigations)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                investigation_id TEXT NOT NULL UNIQUE,
                                objective TEXT NOT NULL,
                                category TEXT NOT NULL DEFAULT 'api',
                                template_id TEXT NOT NULL DEFAULT 'generic',
                                status TEXT NOT NULL DEFAULT 'running',
                                summary TEXT,
                                root_cause TEXT,
                                confidence REAL DEFAULT 0,
                                evidence_json TEXT,
                                recommended_fix TEXT,
                                impact TEXT,
                                ranked_causes_json TEXT,
                                verification_steps_json TEXT,
                                next_action TEXT,
                                proposal_task_id TEXT,
                                proposal_status TEXT,
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            )
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                investigation_id TEXT NOT NULL UNIQUE,
                                objective TEXT NOT NULL,
                                category TEXT NOT NULL DEFAULT 'api',
                                template_id TEXT NOT NULL DEFAULT 'generic',
                                status TEXT NOT NULL DEFAULT 'running',
                                summary TEXT,
                                root_cause TEXT,
                                confidence NUMERIC DEFAULT 0,
                                evidence_json JSONB,
                                recommended_fix TEXT,
                                impact TEXT,
                                ranked_causes_json JSONB,
                                verification_steps_json JSONB,
                                next_action TEXT,
                                proposal_task_id TEXT,
                                proposal_status TEXT,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                    )
            logger.info("[BOOT] Created table %s", tname)
        if table_exists(engine_to_use, tname):
            _ensure_jarvis_investigations_phase4b_columns(engine_to_use)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_investigations_table failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_alerting_tables(engine_to_use) -> bool:
    """Persist Phase 6B Jarvis alerts and daily health reports."""
    if engine_to_use is None:
        logger.warning("ensure_jarvis_alerting_tables: engine is None")
        return False
    try:
        is_sqlite = engine_to_use.dialect.name == "sqlite"
        ts_type = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
        date_type = "TEXT" if is_sqlite else "DATE"
        tables = [
            (
                "jarvis_alerts",
                f"""
                CREATE TABLE IF NOT EXISTS jarvis_alerts (
                    id {'INTEGER PRIMARY KEY AUTOINCREMENT' if is_sqlite else 'SERIAL PRIMARY KEY'},
                    alert_id TEXT NOT NULL UNIQUE,
                    created_at {ts_type} NOT NULL DEFAULT {'CURRENT_TIMESTAMP' if is_sqlite else 'NOW()'},
                    updated_at {ts_type} NOT NULL DEFAULT {'CURRENT_TIMESTAMP' if is_sqlite else 'NOW()'},
                    severity TEXT NOT NULL,
                    source TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    evidence TEXT NOT NULL DEFAULT '[]',
                    investigation_id TEXT,
                    occurrence_count INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'open',
                    first_seen {ts_type} NOT NULL DEFAULT {'CURRENT_TIMESTAMP' if is_sqlite else 'NOW()'},
                    last_seen {ts_type} NOT NULL DEFAULT {'CURRENT_TIMESTAMP' if is_sqlite else 'NOW()'}
                )
                """,
            ),
            (
                "jarvis_daily_reports",
                f"""
                CREATE TABLE IF NOT EXISTS jarvis_daily_reports (
                    id {'INTEGER PRIMARY KEY AUTOINCREMENT' if is_sqlite else 'SERIAL PRIMARY KEY'},
                    report_id TEXT NOT NULL UNIQUE,
                    report_date {date_type} NOT NULL UNIQUE,
                    generated_at {ts_type} NOT NULL DEFAULT {'CURRENT_TIMESTAMP' if is_sqlite else 'NOW()'},
                    summary_json TEXT NOT NULL DEFAULT '{{}}'
                )
                """,
            ),
        ]
        for tname, ddl in tables:
            if not table_exists(engine_to_use, tname):
                logger.warning("Table %s does not exist - creating (Jarvis alerting)", tname)
                with engine_to_use.begin() as conn:
                    conn.execute(text(ddl))
                logger.info("[BOOT] Created table %s", tname)
        return all(table_exists(engine_to_use, tname) for tname, _ in tables)
    except Exception as e:
        logger.error("ensure_jarvis_alerting_tables failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_scheduled_investigations_tables(engine_to_use) -> bool:
    """Persist Phase 6A scheduled investigation schedules, task queue, and leader lock."""
    if engine_to_use is None:
        logger.warning("ensure_jarvis_scheduled_investigations_tables: engine is None")
        return False
    try:
        is_sqlite = engine_to_use.dialect.name == "sqlite"
        bool_type = "INTEGER" if is_sqlite else "BOOLEAN"
        ts_type = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
        tables = [
            (
                "jarvis_investigation_schedules",
                f"""
                CREATE TABLE IF NOT EXISTS jarvis_investigation_schedules (
                    id {'INTEGER PRIMARY KEY AUTOINCREMENT' if is_sqlite else 'SERIAL PRIMARY KEY'},
                    schedule_id TEXT NOT NULL UNIQUE,
                    template_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'api',
                    enabled {bool_type} NOT NULL DEFAULT {'1' if is_sqlite else 'TRUE'},
                    next_run_at {ts_type},
                    last_run_at {ts_type},
                    created_at {ts_type} NOT NULL DEFAULT {'CURRENT_TIMESTAMP' if is_sqlite else 'NOW()'},
                    updated_at {ts_type} NOT NULL DEFAULT {'CURRENT_TIMESTAMP' if is_sqlite else 'NOW()'}
                )
                """,
            ),
            (
                "jarvis_scheduled_investigation_tasks",
                f"""
                CREATE TABLE IF NOT EXISTS jarvis_scheduled_investigation_tasks (
                    id {'INTEGER PRIMARY KEY AUTOINCREMENT' if is_sqlite else 'SERIAL PRIMARY KEY'},
                    task_id TEXT NOT NULL UNIQUE,
                    schedule_id TEXT NOT NULL,
                    template_id TEXT NOT NULL DEFAULT 'generic',
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    investigation_id TEXT,
                    result_summary TEXT,
                    error_message TEXT,
                    scheduled_at {ts_type},
                    started_at {ts_type},
                    completed_at {ts_type},
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    created_at {ts_type} NOT NULL DEFAULT {'CURRENT_TIMESTAMP' if is_sqlite else 'NOW()'},
                    updated_at {ts_type} NOT NULL DEFAULT {'CURRENT_TIMESTAMP' if is_sqlite else 'NOW()'}
                )
                """,
            ),
            (
                "jarvis_investigation_scheduler_leader",
                f"""
                CREATE TABLE IF NOT EXISTS jarvis_investigation_scheduler_leader (
                    lock_key TEXT NOT NULL PRIMARY KEY,
                    holder_id TEXT NOT NULL,
                    acquired_at {ts_type},
                    lease_expires_at {ts_type},
                    updated_at {ts_type} NOT NULL DEFAULT {'CURRENT_TIMESTAMP' if is_sqlite else 'NOW()'}
                )
                """,
            ),
        ]
        for tname, ddl in tables:
            if not table_exists(engine_to_use, tname):
                logger.warning("Table %s does not exist - creating (Jarvis scheduled investigations)", tname)
                with engine_to_use.begin() as conn:
                    conn.execute(text(ddl))
                logger.info("[BOOT] Created table %s", tname)
        return all(table_exists(engine_to_use, tname) for tname, _ in tables)
    except Exception as e:
        logger.error("ensure_jarvis_scheduled_investigations_tables failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_control_center_tables(engine_to_use) -> bool:
    """
    Persist Jarvis Control Center sessions, tasks, approvals, and audit events.

    Uses SQLAlchemy models (create_all) in FK order. Returns True if all four tables exist.
    """
    if engine_to_use is None:
        logger.warning("ensure_jarvis_control_center_tables: engine is None")
        return False
    try:
        from app.models.jarvis_control_models import (
            JarvisControlApproval,
            JarvisControlAuditEvent,
            JarvisControlSession,
            JarvisControlTask,
        )

        ordered = [
            (JarvisControlSession, "jarvis_control_sessions"),
            (JarvisControlTask, "jarvis_control_tasks"),
            (JarvisControlApproval, "jarvis_control_approvals"),
            (JarvisControlAuditEvent, "jarvis_control_audit_events"),
        ]
        for model, tname in ordered:
            tbl = getattr(model, "__table__", None)
            if tbl is None:
                logger.error("ensure_jarvis_control_center_tables: missing table for %s", tname)
                return False
            if not table_exists(engine_to_use, tname):
                logger.warning(
                    "Table %s does not exist - creating (Jarvis Control Center)",
                    tname,
                )
                Base.metadata.create_all(bind=engine_to_use, tables=[tbl])
                logger.info("[BOOT] Created table %s", tname)
        if not _ensure_jarvis_control_task_artifact_columns(engine_to_use):
            logger.warning("ensure_jarvis_control_center_tables: artifact columns not fully applied")
        if not ensure_jarvis_control_approval_comment_column(engine_to_use):
            logger.warning(
                "ensure_jarvis_control_center_tables: approval comment column not fully applied"
            )
        return all(table_exists(engine_to_use, tname) for _, tname in ordered)
    except Exception as e:
        logger.error("ensure_jarvis_control_center_tables failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_control_approval_comment_column(engine_to_use) -> bool:
    """Add comment to jarvis_control_approvals if missing (Step 1 tables without Step 7 column)."""
    if engine_to_use is None:
        return False
    if not table_exists(engine_to_use, "jarvis_control_approvals"):
        return False
    try:
        inspector = inspect(engine_to_use)
        columns = {col["name"] for col in inspector.get_columns("jarvis_control_approvals")}
        if "comment" in columns:
            return True
        col_def = "TEXT"
        with engine_to_use.begin() as conn:
            if engine_to_use.dialect.name == "postgresql":
                conn.execute(
                    text(
                        "ALTER TABLE jarvis_control_approvals "
                        "ADD COLUMN IF NOT EXISTS comment TEXT"
                    )
                )
            else:
                conn.execute(
                    text(f"ALTER TABLE jarvis_control_approvals ADD COLUMN comment {col_def}")
                )
        logger.info("[BOOT] Added jarvis_control_approvals.comment column")
        return True
    except Exception as e:
        logger.warning("ensure_jarvis_control_approval_comment_column failed: %s", e)
        return False


def _ensure_jarvis_control_task_artifact_columns(engine_to_use) -> bool:
    """Add artifact_version and artifact_updated_at to jarvis_control_tasks if missing."""
    if engine_to_use is None:
        return False
    if not table_exists(engine_to_use, "jarvis_control_tasks"):
        return False
    try:
        inspector = inspect(engine_to_use)
        columns = {col["name"] for col in inspector.get_columns("jarvis_control_tasks")}
        additions: list[tuple[str, str]] = []
        if "artifact_version" not in columns:
            additions.append(("artifact_version", "INTEGER NOT NULL DEFAULT 0"))
        if "artifact_updated_at" not in columns:
            if engine_to_use.dialect.name == "sqlite":
                additions.append(("artifact_updated_at", "TIMESTAMP"))
            else:
                additions.append(("artifact_updated_at", "TIMESTAMPTZ"))
        if not additions:
            return True
        with engine_to_use.begin() as conn:
            for col_name, col_def in additions:
                conn.execute(
                    text(f"ALTER TABLE jarvis_control_tasks ADD COLUMN {col_name} {col_def}")
                )
        logger.info(
            "[BOOT] Added jarvis_control_tasks artifact columns: %s",
            [a[0] for a in additions],
        )
        return True
    except Exception as e:
        logger.warning("_ensure_jarvis_control_task_artifact_columns failed: %s", e)
        return False


def ensure_jarvis_audit_runs_table(engine_to_use) -> bool:
    """
    Persist Jarvis AWS Auditor run history.

    Returns True if the table exists after this call.
    """
    if engine_to_use is None:
        logger.warning("ensure_jarvis_audit_runs_table: engine is None")
        return False
    tname = "jarvis_audit_runs"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Jarvis audit runs)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                audit_id TEXT NOT NULL UNIQUE,
                                task_id TEXT,
                                summary_json TEXT,
                                cost_findings_json TEXT,
                                security_findings_json TEXT,
                                resource_findings_json TEXT,
                                recommendations_json TEXT,
                                estimated_monthly_savings REAL,
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(f"CREATE INDEX IF NOT EXISTS ix_jarvis_audit_runs_created_at ON {tname} (created_at DESC)")
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                audit_id TEXT NOT NULL UNIQUE,
                                task_id TEXT,
                                summary_json JSONB,
                                cost_findings_json JSONB,
                                security_findings_json JSONB,
                                resource_findings_json JSONB,
                                recommendations_json JSONB,
                                estimated_monthly_savings NUMERIC,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(f"CREATE INDEX IF NOT EXISTS ix_jarvis_audit_runs_created_at ON {tname} (created_at DESC)")
                    )
            logger.info("[BOOT] Created table %s", tname)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_audit_runs_table failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_daily_metrics_table(engine_to_use) -> bool:
    """
    Persist Jarvis executive daily metrics snapshots.

    Returns True if the table exists after this call.
    """
    if engine_to_use is None:
        logger.warning("ensure_jarvis_daily_metrics_table: engine is None")
        return False
    tname = "jarvis_daily_metrics"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Jarvis daily metrics)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                metric_date TEXT NOT NULL UNIQUE,
                                aws_monthly_cost REAL,
                                aws_daily_cost REAL,
                                ec2_count INTEGER,
                                ebs_count INTEGER,
                                snapshot_count INTEGER,
                                eip_count INTEGER,
                                open_findings INTEGER,
                                critical_findings INTEGER,
                                task_count INTEGER,
                                audit_count INTEGER,
                                task_success_rate REAL,
                                bedrock_cost REAL,
                                dashboard_portfolio_value REAL,
                                exchange_portfolio_value REAL,
                                portfolio_difference_pct REAL,
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(f"CREATE INDEX IF NOT EXISTS ix_jarvis_daily_metrics_date ON {tname} (metric_date DESC)")
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                metric_date DATE NOT NULL UNIQUE,
                                aws_monthly_cost NUMERIC,
                                aws_daily_cost NUMERIC,
                                ec2_count INTEGER,
                                ebs_count INTEGER,
                                snapshot_count INTEGER,
                                eip_count INTEGER,
                                open_findings INTEGER,
                                critical_findings INTEGER,
                                task_count INTEGER,
                                audit_count INTEGER,
                                task_success_rate NUMERIC,
                                bedrock_cost NUMERIC,
                                dashboard_portfolio_value NUMERIC,
                                exchange_portfolio_value NUMERIC,
                                portfolio_difference_pct NUMERIC,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(f"CREATE INDEX IF NOT EXISTS ix_jarvis_daily_metrics_date ON {tname} (metric_date DESC)")
                    )
            logger.info("[BOOT] Created table %s", tname)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_daily_metrics_table failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_crypto_audit_runs_table(engine_to_use) -> bool:
    """
    Persist Jarvis Crypto Auditor run history.

    Returns True if the table exists after this call.
    """
    if engine_to_use is None:
        logger.warning("ensure_jarvis_crypto_audit_runs_table: engine is None")
        return False
    tname = "jarvis_crypto_audit_runs"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Jarvis crypto audit runs)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                audit_id TEXT NOT NULL UNIQUE,
                                task_id TEXT,
                                summary_json TEXT,
                                wallet_findings_json TEXT,
                                position_findings_json TEXT,
                                valuation_findings_json TEXT,
                                price_feed_findings_json TEXT,
                                recommendations_json TEXT,
                                portfolio_difference_usd REAL,
                                portfolio_difference_pct REAL,
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_crypto_audit_runs_created_at ON {tname} (created_at DESC)"
                        )
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                audit_id TEXT NOT NULL UNIQUE,
                                task_id TEXT,
                                summary_json JSONB,
                                wallet_findings_json JSONB,
                                position_findings_json JSONB,
                                valuation_findings_json JSONB,
                                price_feed_findings_json JSONB,
                                recommendations_json JSONB,
                                portfolio_difference_usd NUMERIC,
                                portfolio_difference_pct NUMERIC,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_crypto_audit_runs_created_at ON {tname} (created_at DESC)"
                        )
                    )
            logger.info("[BOOT] Created table %s", tname)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_crypto_audit_runs_table failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_action_plans_table(engine_to_use) -> bool:
    """
    Persist Jarvis Action Planner remediation recommendations.

    Returns True if the table exists after this call.
    """
    if engine_to_use is None:
        logger.warning("ensure_jarvis_action_plans_table: engine is None")
        return False
    tname = "jarvis_action_plans"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Jarvis action plans)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                plan_id TEXT NOT NULL UNIQUE,
                                source_type TEXT,
                                source_id TEXT,
                                severity TEXT,
                                estimated_savings_usd REAL,
                                estimated_risk_reduction TEXT,
                                actions_json TEXT,
                                status TEXT NOT NULL DEFAULT 'proposed',
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_action_plans_created_at ON {tname} (created_at DESC)"
                        )
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                plan_id TEXT NOT NULL UNIQUE,
                                source_type TEXT,
                                source_id TEXT,
                                severity TEXT,
                                estimated_savings_usd NUMERIC,
                                estimated_risk_reduction TEXT,
                                actions_json JSONB,
                                status TEXT NOT NULL DEFAULT 'proposed',
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_action_plans_created_at ON {tname} (created_at DESC)"
                        )
                    )
            logger.info("[BOOT] Created table %s", tname)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_action_plans_table failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_decisions_table(engine_to_use) -> bool:
    """
    Persist Jarvis human decision records for decision intelligence.

    Returns True if the table exists after this call.
    """
    if engine_to_use is None:
        logger.warning("ensure_jarvis_decisions_table: engine is None")
        return False
    tname = "jarvis_decisions"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Jarvis decisions)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                decision_id TEXT NOT NULL UNIQUE,
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                source_type TEXT,
                                source_id TEXT,
                                plan_id TEXT,
                                decision TEXT NOT NULL,
                                decision_reason TEXT,
                                outcome TEXT NOT NULL DEFAULT 'unknown',
                                reviewed_at TIMESTAMP,
                                reviewed_by TEXT
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_decisions_created_at "
                            f"ON {tname} (created_at DESC)"
                        )
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                decision_id TEXT NOT NULL UNIQUE,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                source_type TEXT,
                                source_id TEXT,
                                plan_id TEXT,
                                decision TEXT NOT NULL,
                                decision_reason TEXT,
                                outcome TEXT NOT NULL DEFAULT 'unknown',
                                reviewed_at TIMESTAMPTZ,
                                reviewed_by TEXT
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_decisions_created_at "
                            f"ON {tname} (created_at DESC)"
                        )
                    )
            logger.info("[BOOT] Created table %s", tname)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_decisions_table failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_initiatives_table(engine_to_use) -> bool:
    """
    Persist Jarvis initiatives for the Operating System management layer.

    Returns True if the table exists after this call.
    """
    if engine_to_use is None:
        logger.warning("ensure_jarvis_initiatives_table: engine is None")
        return False
    tname = "jarvis_initiatives"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Jarvis initiatives)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                initiative_id TEXT NOT NULL UNIQUE,
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                title TEXT NOT NULL,
                                description TEXT,
                                status TEXT NOT NULL DEFAULT 'planned',
                                priority TEXT NOT NULL DEFAULT 'medium',
                                owner TEXT,
                                target_date TEXT,
                                source_type TEXT,
                                source_id TEXT,
                                progress_pct INTEGER NOT NULL DEFAULT 0,
                                health TEXT NOT NULL DEFAULT 'green',
                                blocked_reason TEXT
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_initiatives_updated_at "
                            f"ON {tname} (updated_at DESC)"
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_initiatives_status "
                            f"ON {tname} (status)"
                        )
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                initiative_id TEXT NOT NULL UNIQUE,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                title TEXT NOT NULL,
                                description TEXT,
                                status TEXT NOT NULL DEFAULT 'planned',
                                priority TEXT NOT NULL DEFAULT 'medium',
                                owner TEXT,
                                target_date DATE,
                                source_type TEXT,
                                source_id TEXT,
                                progress_pct INTEGER NOT NULL DEFAULT 0,
                                health TEXT NOT NULL DEFAULT 'green',
                                blocked_reason TEXT
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_initiatives_updated_at "
                            f"ON {tname} (updated_at DESC)"
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_initiatives_status "
                            f"ON {tname} (status)"
                        )
                    )
            logger.info("[BOOT] Created table %s", tname)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_initiatives_table failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_executive_reports_table(engine_to_use) -> bool:
    """
    Persist Jarvis Chief of Staff weekly executive priority reports.

    Returns True if the table exists after this call.
    """
    if engine_to_use is None:
        logger.warning("ensure_jarvis_executive_reports_table: engine is None")
        return False
    tname = "jarvis_executive_reports"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Jarvis executive reports)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                report_id TEXT NOT NULL UNIQUE,
                                generated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                overall_health_score INTEGER NOT NULL DEFAULT 0,
                                top_priorities_json TEXT,
                                quick_wins_json TEXT,
                                strategic_items_json TEXT,
                                blocked_items_json TEXT,
                                lessons_learned_json TEXT
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_executive_reports_generated_at "
                            f"ON {tname} (generated_at DESC)"
                        )
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                report_id TEXT NOT NULL UNIQUE,
                                generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                overall_health_score INTEGER NOT NULL DEFAULT 0,
                                top_priorities_json JSONB,
                                quick_wins_json JSONB,
                                strategic_items_json JSONB,
                                blocked_items_json JSONB,
                                lessons_learned_json JSONB
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_executive_reports_generated_at "
                            f"ON {tname} (generated_at DESC)"
                        )
                    )
            logger.info("[BOOT] Created table %s", tname)
        if table_exists(engine_to_use, tname) and not table_has_column(engine_to_use, tname, "lessons_learned_json"):
            logger.warning("Column lessons_learned_json missing on %s - adding", tname)
            with engine_to_use.begin() as conn:
                col_type = "TEXT" if engine_to_use.dialect.name == "sqlite" else "JSONB"
                conn.execute(text(f"ALTER TABLE {tname} ADD COLUMN lessons_learned_json {col_type}"))
        for col in ("execution_review_json", "execution_status_json"):
            if table_exists(engine_to_use, tname) and not table_has_column(engine_to_use, tname, col):
                logger.warning("Column %s missing on %s - adding", col, tname)
                with engine_to_use.begin() as conn:
                    col_type = "TEXT" if engine_to_use.dialect.name == "sqlite" else "JSONB"
                    conn.execute(text(f"ALTER TABLE {tname} ADD COLUMN {col} {col_type}"))
        for col in ("followup_review_json", "strategic_alignment_json"):
            if table_exists(engine_to_use, tname) and not table_has_column(engine_to_use, tname, col):
                logger.warning("Column %s missing on %s - adding", col, tname)
                with engine_to_use.begin() as conn:
                    col_type = "TEXT" if engine_to_use.dialect.name == "sqlite" else "JSONB"
                    conn.execute(text(f"ALTER TABLE {tname} ADD COLUMN {col} {col_type}"))
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_executive_reports_table failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_followups_table(engine_to_use) -> bool:
    """
    Persist Jarvis follow-up reminders (read-only management layer).

    Returns True if the table exists after this call.
    """
    if engine_to_use is None:
        logger.warning("ensure_jarvis_followups_table: engine is None")
        return False
    tname = "jarvis_followups"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Jarvis follow-ups)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                followup_id TEXT NOT NULL UNIQUE,
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                source_type TEXT NOT NULL,
                                source_id TEXT,
                                title TEXT NOT NULL,
                                description TEXT,
                                severity TEXT NOT NULL DEFAULT 'medium',
                                status TEXT NOT NULL DEFAULT 'open',
                                due_date TEXT,
                                assigned_to TEXT,
                                reminder_count INTEGER NOT NULL DEFAULT 0,
                                last_reminded_at TIMESTAMP
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_followups_status "
                            f"ON {tname} (status)"
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_followups_severity "
                            f"ON {tname} (severity)"
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_followups_updated_at "
                            f"ON {tname} (updated_at DESC)"
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE UNIQUE INDEX IF NOT EXISTS ix_jarvis_followups_dedup "
                            f"ON {tname} (source_type, source_id, title) "
                            f"WHERE status = 'open'"
                        )
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                followup_id TEXT NOT NULL UNIQUE,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                source_type TEXT NOT NULL,
                                source_id TEXT,
                                title TEXT NOT NULL,
                                description TEXT,
                                severity TEXT NOT NULL DEFAULT 'medium',
                                status TEXT NOT NULL DEFAULT 'open',
                                due_date DATE,
                                assigned_to TEXT,
                                reminder_count INTEGER NOT NULL DEFAULT 0,
                                last_reminded_at TIMESTAMPTZ
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_followups_status "
                            f"ON {tname} (status)"
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_followups_severity "
                            f"ON {tname} (severity)"
                        )
                    )
                    conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_jarvis_followups_updated_at "
                            f"ON {tname} (updated_at DESC)"
                        )
                    )
                    conn.execute(
                        text(
                            f"""
                            CREATE UNIQUE INDEX IF NOT EXISTS ix_jarvis_followups_dedup
                            ON {tname} (source_type, COALESCE(source_id, ''), title)
                            WHERE status = 'open'
                            """
                        )
                    )
            logger.info("[BOOT] Created table %s", tname)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_followups_table failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_objectives_table(engine_to_use) -> bool:
    """Persist Jarvis strategic objectives (read-only management layer)."""
    if engine_to_use is None:
        logger.warning("ensure_jarvis_objectives_table: engine is None")
        return False
    tname = "jarvis_objectives"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Jarvis objectives)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                objective_id TEXT NOT NULL UNIQUE,
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                title TEXT NOT NULL,
                                description TEXT,
                                status TEXT NOT NULL DEFAULT 'planned',
                                owner TEXT,
                                target_date TEXT,
                                progress_pct INTEGER NOT NULL DEFAULT 0,
                                health TEXT NOT NULL DEFAULT 'green'
                            )
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                objective_id TEXT NOT NULL UNIQUE,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                title TEXT NOT NULL,
                                description TEXT,
                                status TEXT NOT NULL DEFAULT 'planned',
                                owner TEXT,
                                target_date DATE,
                                progress_pct INTEGER NOT NULL DEFAULT 0,
                                health TEXT NOT NULL DEFAULT 'green'
                            )
                            """
                        )
                    )
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS ix_jarvis_objectives_status "
                        f"ON {tname} (status)"
                    )
                )
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS ix_jarvis_objectives_updated_at "
                        f"ON {tname} (updated_at DESC)"
                    )
                )
            logger.info("[BOOT] Created table %s", tname)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_objectives_table failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_key_results_table(engine_to_use) -> bool:
    """Persist measurable key results for Jarvis objectives."""
    if engine_to_use is None:
        logger.warning("ensure_jarvis_key_results_table: engine is None")
        return False
    tname = "jarvis_key_results"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Jarvis key results)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                kr_id TEXT NOT NULL UNIQUE,
                                objective_id TEXT NOT NULL,
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                title TEXT NOT NULL,
                                metric_name TEXT,
                                target_value REAL NOT NULL DEFAULT 0,
                                current_value REAL NOT NULL DEFAULT 0,
                                unit TEXT,
                                direction TEXT NOT NULL DEFAULT 'max',
                                status TEXT NOT NULL DEFAULT 'on_track'
                            )
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                kr_id TEXT NOT NULL UNIQUE,
                                objective_id TEXT NOT NULL,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                title TEXT NOT NULL,
                                metric_name TEXT,
                                target_value DOUBLE PRECISION NOT NULL DEFAULT 0,
                                current_value DOUBLE PRECISION NOT NULL DEFAULT 0,
                                unit TEXT,
                                direction TEXT NOT NULL DEFAULT 'max',
                                status TEXT NOT NULL DEFAULT 'on_track'
                            )
                            """
                        )
                    )
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS ix_jarvis_key_results_objective_id "
                        f"ON {tname} (objective_id)"
                    )
                )
            logger.info("[BOOT] Created table %s", tname)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_key_results_table failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_objective_links_table(engine_to_use) -> bool:
    """Link objectives to initiatives, audits, plans, decisions, and reports."""
    if engine_to_use is None:
        logger.warning("ensure_jarvis_objective_links_table: engine is None")
        return False
    tname = "jarvis_objective_links"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Jarvis objective links)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                link_id TEXT NOT NULL UNIQUE,
                                objective_id TEXT NOT NULL,
                                linked_type TEXT NOT NULL,
                                linked_id TEXT NOT NULL,
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            )
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                link_id TEXT NOT NULL UNIQUE,
                                objective_id TEXT NOT NULL,
                                linked_type TEXT NOT NULL,
                                linked_id TEXT NOT NULL,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                    )
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS ix_jarvis_objective_links_objective_id "
                        f"ON {tname} (objective_id)"
                    )
                )
                conn.execute(
                    text(
                        f"CREATE UNIQUE INDEX IF NOT EXISTS ix_jarvis_objective_links_unique "
                        f"ON {tname} (objective_id, linked_type, linked_id)"
                    )
                )
            logger.info("[BOOT] Created table %s", tname)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_objective_links_table failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_kr_refresh_runs_table(engine_to_use) -> bool:
    """Log read-only KR metric refresh runs."""
    if engine_to_use is None:
        logger.warning("ensure_jarvis_kr_refresh_runs_table: engine is None")
        return False
    tname = "jarvis_kr_refresh_runs"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Jarvis KR refresh runs)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                refresh_id TEXT NOT NULL UNIQUE,
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                kr_count INTEGER NOT NULL DEFAULT 0,
                                updated_count INTEGER NOT NULL DEFAULT 0,
                                failed_count INTEGER NOT NULL DEFAULT 0,
                                errors_json TEXT
                            )
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                refresh_id TEXT NOT NULL UNIQUE,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                kr_count INTEGER NOT NULL DEFAULT 0,
                                updated_count INTEGER NOT NULL DEFAULT 0,
                                failed_count INTEGER NOT NULL DEFAULT 0,
                                errors_json TEXT
                            )
                            """
                        )
                    )
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS ix_jarvis_kr_refresh_runs_created "
                        f"ON {tname} (created_at DESC)"
                    )
                )
            logger.info("[BOOT] Created table %s", tname)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_kr_refresh_runs_table failed: %s", e, exc_info=True)
        return False


def ensure_jarvis_key_results_metric_columns(engine_to_use) -> bool:
    """Add metric_source and last_refreshed_at columns to jarvis_key_results if missing."""
    if engine_to_use is None:
        return False
    if not table_exists(engine_to_use, "jarvis_key_results"):
        return False
    try:
        inspector = inspect(engine_to_use)
        columns = {col["name"] for col in inspector.get_columns("jarvis_key_results")}
        additions: list[tuple[str, str]] = []
        if "metric_source" not in columns:
            additions.append(("metric_source", "TEXT"))
        if "last_refreshed_at" not in columns:
            if engine_to_use.dialect.name == "sqlite":
                additions.append(("last_refreshed_at", "TIMESTAMP"))
            else:
                additions.append(("last_refreshed_at", "TIMESTAMPTZ"))
        if not additions:
            return True
        with engine_to_use.begin() as conn:
            for col_name, col_type in additions:
                conn.execute(
                    text(f"ALTER TABLE jarvis_key_results ADD COLUMN {col_name} {col_type}")
                )
        logger.info("[BOOT] Added jarvis_key_results columns: %s", [a[0] for a in additions])
        return True
    except Exception as e:
        logger.warning("ensure_jarvis_key_results_metric_columns failed: %s", e)
        return False


def ensure_jarvis_objective_metrics_table(engine_to_use) -> bool:
    """Time-series snapshots of objective progress for trend charts."""
    if engine_to_use is None:
        logger.warning("ensure_jarvis_objective_metrics_table: engine is None")
        return False
    tname = "jarvis_objective_metrics"
    try:
        if not table_exists(engine_to_use, tname):
            logger.warning("Table %s does not exist - creating (Jarvis objective metrics)", tname)
            with engine_to_use.begin() as conn:
                if engine_to_use.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                metric_id TEXT NOT NULL UNIQUE,
                                objective_id TEXT NOT NULL,
                                metric_date TEXT NOT NULL,
                                progress_pct INTEGER NOT NULL DEFAULT 0,
                                health TEXT NOT NULL DEFAULT 'green',
                                on_track_krs INTEGER NOT NULL DEFAULT 0,
                                at_risk_krs INTEGER NOT NULL DEFAULT 0,
                                behind_krs INTEGER NOT NULL DEFAULT 0,
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            )
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS {tname} (
                                id SERIAL PRIMARY KEY,
                                metric_id TEXT NOT NULL UNIQUE,
                                objective_id TEXT NOT NULL,
                                metric_date DATE NOT NULL,
                                progress_pct INTEGER NOT NULL DEFAULT 0,
                                health TEXT NOT NULL DEFAULT 'green',
                                on_track_krs INTEGER NOT NULL DEFAULT 0,
                                at_risk_krs INTEGER NOT NULL DEFAULT 0,
                                behind_krs INTEGER NOT NULL DEFAULT 0,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                    )
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS ix_jarvis_objective_metrics_objective_date "
                        f"ON {tname} (objective_id, metric_date DESC)"
                    )
                )
            logger.info("[BOOT] Created table %s", tname)
        return table_exists(engine_to_use, tname)
    except Exception as e:
        logger.error("ensure_jarvis_objective_metrics_table failed: %s", e, exc_info=True)
        return False


def ensure_optional_columns(db_engine=None):
    """
    Ensure optional columns exist in critical tables.
    This guards against environments that haven't run the latest migrations.
    
    Also ensures critical tables exist (e.g., order_intents).
    """
    engine_to_use = db_engine or engine
    if engine_to_use is None:
        logger.warning("Cannot ensure optional columns - engine is None")
        return
    
    try:
        from app.models.watchlist import WatchlistItem
        from app.models.telegram_message import TelegramMessage
        from app.models.signal_throttle import SignalThrottleState
        from app.models.order_intent import OrderIntent
        from app.models.agent_approval_state import AgentApprovalState
    except Exception as import_err:
        logger.warning(f"Cannot load models to verify optional columns: {import_err}")
        return

    # Ensure agent_approval_states exists (required for Telegram approval flow and scheduler)
    agent_approval_table = getattr(getattr(AgentApprovalState, "__table__", None), "name", None) or "agent_approval_states"
    try:
        if not table_exists(engine_to_use, agent_approval_table):
            logger.warning(f"Table {agent_approval_table} does not exist - creating it")
            Base.metadata.create_all(bind=engine_to_use, tables=[AgentApprovalState.__table__])
            logger.info(f"[BOOT] Created table {agent_approval_table}")
        else:
            logger.info(f"[BOOT] {agent_approval_table} table OK")
    except Exception as table_err:
        logger.error(f"Error ensuring {agent_approval_table} table exists: {table_err}", exc_info=True)

    # Governance tables (tasks, events, manifests) — see backend/migrations/20260322_create_governance_tables.sql
    try:
        from app.models.governance_models import GovernanceEvent, GovernanceManifest, GovernanceTask

        for model, tname in [
            (GovernanceTask, "governance_tasks"),
            (GovernanceEvent, "governance_events"),
            (GovernanceManifest, "governance_manifests"),
        ]:
            tbl = getattr(model, "__table__", None)
            if tbl and not table_exists(engine_to_use, tname):
                logger.warning("Table %s does not exist - creating (governance)", tname)
                Base.metadata.create_all(bind=engine_to_use, tables=[tbl])
                logger.info("[BOOT] Created table %s", tname)
    except Exception as gov_err:
        logger.warning("Could not ensure governance tables: %s", gov_err)

    # Telegram poller dedup (backend/migrations/add_telegram_update_dedup.sql) — missing table aborts txn on INSERT
    try:
        if ensure_telegram_update_dedup_table(engine_to_use):
            logger.info("[BOOT] telegram_update_dedup table OK")
        else:
            logger.error(
                "[BOOT] telegram_update_dedup missing after ensure — Telegram dedup INSERT will fail until fixed"
            )
    except Exception as dedup_err:
        logger.warning("Could not ensure telegram_update_dedup table: %s", dedup_err)

    try:
        if ensure_jarvis_marketing_intake_table(engine_to_use):
            logger.info("[BOOT] jarvis_marketing_intake_state table OK")
    except Exception as intake_err:
        logger.warning("Could not ensure jarvis_marketing_intake_state table: %s", intake_err)

    try:
        if ensure_jarvis_task_runs_table(engine_to_use):
            logger.info("[BOOT] jarvis_task_runs table OK")
    except Exception as task_runs_err:
        logger.warning("Could not ensure jarvis_task_runs table: %s", task_runs_err)

    try:
        if ensure_jarvis_execution_log_table(engine_to_use):
            logger.info("[BOOT] jarvis_execution_log table OK")
    except Exception as exec_log_err:
        logger.warning("Could not ensure jarvis_execution_log table: %s", exec_log_err)

    try:
        if ensure_jarvis_task_approvals_table(engine_to_use):
            logger.info("[BOOT] jarvis_task_approvals table OK")
    except Exception as approvals_err:
        logger.warning("Could not ensure jarvis_task_approvals table: %s", approvals_err)

    try:
        if ensure_jarvis_investigations_table(engine_to_use):
            logger.info("[BOOT] jarvis_investigations table OK")
    except Exception as investigations_err:
        logger.warning("Could not ensure jarvis_investigations table: %s", investigations_err)

    try:
        if ensure_jarvis_control_center_tables(engine_to_use):
            logger.info("[BOOT] jarvis_control_* tables OK")
    except Exception as control_center_err:
        logger.warning("Could not ensure jarvis_control_* tables: %s", control_center_err)

    try:
        if ensure_jarvis_audit_runs_table(engine_to_use):
            logger.info("[BOOT] jarvis_audit_runs table OK")
    except Exception as audit_runs_err:
        logger.warning("Could not ensure jarvis_audit_runs table: %s", audit_runs_err)

    try:
        if ensure_jarvis_daily_metrics_table(engine_to_use):
            logger.info("[BOOT] jarvis_daily_metrics table OK")
    except Exception as daily_metrics_err:
        logger.warning("Could not ensure jarvis_daily_metrics table: %s", daily_metrics_err)

    try:
        if ensure_jarvis_crypto_audit_runs_table(engine_to_use):
            logger.info("[BOOT] jarvis_crypto_audit_runs table OK")
    except Exception as crypto_audit_err:
        logger.warning("Could not ensure jarvis_crypto_audit_runs table: %s", crypto_audit_err)

    try:
        if ensure_jarvis_action_plans_table(engine_to_use):
            logger.info("[BOOT] jarvis_action_plans table OK")
    except Exception as action_plans_err:
        logger.warning("Could not ensure jarvis_action_plans table: %s", action_plans_err)

    try:
        if ensure_jarvis_executive_reports_table(engine_to_use):
            logger.info("[BOOT] jarvis_executive_reports table OK")
    except Exception as executive_reports_err:
        logger.warning("Could not ensure jarvis_executive_reports table: %s", executive_reports_err)

    try:
        if ensure_jarvis_decisions_table(engine_to_use):
            logger.info("[BOOT] jarvis_decisions table OK")
    except Exception as decisions_err:
        logger.warning("Could not ensure jarvis_decisions table: %s", decisions_err)

    try:
        if ensure_jarvis_initiatives_table(engine_to_use):
            logger.info("[BOOT] jarvis_initiatives table OK")
    except Exception as initiatives_err:
        logger.warning("Could not ensure jarvis_initiatives table: %s", initiatives_err)

    try:
        if ensure_jarvis_followups_table(engine_to_use):
            logger.info("[BOOT] jarvis_followups table OK")
    except Exception as followups_err:
        logger.warning("Could not ensure jarvis_followups table: %s", followups_err)

    try:
        if ensure_jarvis_objectives_table(engine_to_use):
            logger.info("[BOOT] jarvis_objectives table OK")
    except Exception as objectives_err:
        logger.warning("Could not ensure jarvis_objectives table: %s", objectives_err)

    try:
        if ensure_jarvis_key_results_table(engine_to_use):
            logger.info("[BOOT] jarvis_key_results table OK")
    except Exception as key_results_err:
        logger.warning("Could not ensure jarvis_key_results table: %s", key_results_err)

    try:
        if ensure_jarvis_objective_links_table(engine_to_use):
            logger.info("[BOOT] jarvis_objective_links table OK")
    except Exception as objective_links_err:
        logger.warning("Could not ensure jarvis_objective_links table: %s", objective_links_err)

    try:
        if ensure_jarvis_objective_metrics_table(engine_to_use):
            logger.info("[BOOT] jarvis_objective_metrics table OK")
    except Exception as objective_metrics_err:
        logger.warning("Could not ensure jarvis_objective_metrics table: %s", objective_metrics_err)

    try:
        if ensure_jarvis_kr_refresh_runs_table(engine_to_use):
            logger.info("[BOOT] jarvis_kr_refresh_runs table OK")
    except Exception as kr_refresh_err:
        logger.warning("Could not ensure jarvis_kr_refresh_runs table: %s", kr_refresh_err)

    try:
        if ensure_jarvis_key_results_metric_columns(engine_to_use):
            logger.info("[BOOT] jarvis_key_results metric columns OK")
    except Exception as kr_cols_err:
        logger.warning("Could not ensure jarvis_key_results metric columns: %s", kr_cols_err)

    watchlist_table = getattr(getattr(WatchlistItem, "__table__", None), "name", None) or getattr(
        WatchlistItem, "__tablename__", "watchlist_items"
    )
    # Create watchlist_items first (market-updater and signal_monitor depend on it); then market tables; then order_intents.
    # Order matters: optional_columns loop below ALTERs these tables, so they must exist.
    try:
        if not table_exists(engine_to_use, watchlist_table):
            logger.warning(f"Table {watchlist_table} does not exist - creating it")
            Base.metadata.create_all(bind=engine_to_use, tables=[WatchlistItem.__table__])
            logger.info(f"[BOOT] Created table {watchlist_table}")
        else:
            logger.info(f"[BOOT] {watchlist_table} table OK")
    except Exception as table_err:
        logger.error(f"Error ensuring {watchlist_table} table exists: {table_err}", exc_info=True)

    try:
        from app.models.market_price import MarketData, MarketPrice
        for model, name in [(MarketData, "market_data"), (MarketPrice, "market_price")]:
            tbl = getattr(model, "__table__", None)
            tname = getattr(model, "__tablename__", name)
            if tbl and not table_exists(engine_to_use, tname):
                logger.warning(f"Table {tname} does not exist - creating it")
                Base.metadata.create_all(bind=engine_to_use, tables=[tbl])
                logger.info(f"[BOOT] Created table {tname}")
    except Exception as table_err:
        logger.warning(f"Could not ensure market_data/market_price tables: {table_err}")

    # Ensure order_intents table exists. If create_all fails (e.g. orphan index), try drop+retry;
    # if that still fails, create table and indexes via raw SQL with IF NOT EXISTS.
    order_intents_table = getattr(getattr(OrderIntent, "__table__", None), "name", None) or getattr(
        OrderIntent, "__tablename__", "order_intents"
    )
    try:
        if not table_exists(engine_to_use, order_intents_table):
            logger.warning(f"Table {order_intents_table} does not exist - creating it")
            created = False
            try:
                Base.metadata.create_all(bind=engine_to_use, tables=[OrderIntent.__table__])
                created = True
                logger.info(f"[BOOT] Created table {order_intents_table}")
            except Exception as create_err:
                err_msg = str(create_err)
                if "ix_order_intents_signal_id" in err_msg and "already exists" in err_msg:
                    try:
                        with engine_to_use.begin() as conn:
                            conn.execute(text("DROP INDEX IF EXISTS ix_order_intents_signal_id CASCADE"))
                            Base.metadata.create_all(bind=conn, tables=[OrderIntent.__table__])
                        created = True
                        logger.info(f"[BOOT] Created table {order_intents_table} after dropping orphan index")
                    except Exception as retry_err:
                        logger.warning("Drop+retry failed, creating order_intents via raw SQL: %s", retry_err)
                        with engine_to_use.begin() as conn:
                            conn.execute(text("""
                                CREATE TABLE IF NOT EXISTS order_intents (
                                    id SERIAL PRIMARY KEY,
                                    idempotency_key VARCHAR(200) NOT NULL,
                                    signal_id INTEGER,
                                    symbol VARCHAR(50) NOT NULL,
                                    side VARCHAR(10) NOT NULL,
                                    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                                    order_id VARCHAR(100),
                                    error_message TEXT,
                                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                                    UNIQUE(idempotency_key)
                                )
                            """))
                            for idx_sql in (
                                "CREATE INDEX IF NOT EXISTS ix_order_intents_signal_id ON order_intents (signal_id)",
                                "CREATE INDEX IF NOT EXISTS ix_order_intents_symbol_side ON order_intents (symbol, side)",
                            ):
                                conn.execute(text(idx_sql))
                        created = True
                        logger.info(f"[BOOT] Created table {order_intents_table} via raw SQL")
                if not created:
                    raise
        else:
            logger.info(f"[BOOT] order_intents table OK")
    except Exception as table_err:
        logger.error(f"Error ensuring order_intents table exists: {table_err}", exc_info=True)

    table_configs = {}
    table_configs[watchlist_table] = [
        ("is_deleted", "BOOLEAN NOT NULL DEFAULT false"),
        ("min_price_change_pct", "DOUBLE PRECISION"),
    ]
    
    telegram_table = getattr(getattr(TelegramMessage, "__table__", None), "name", None) or getattr(
        TelegramMessage, "__tablename__", "telegram_messages"
    )
    table_configs[telegram_table] = [
        ("throttle_status", "VARCHAR(20)"),
        ("throttle_reason", "TEXT"),
    ]

    throttle_table = getattr(getattr(SignalThrottleState, "__table__", None), "name", None) or getattr(
        SignalThrottleState, "__tablename__", "signal_throttle_states"
    )
    table_configs[throttle_table] = [
        ("config_hash", "VARCHAR(128)")
    ]
    
    try:
        with engine_to_use.begin() as conn:
            for table_name, optional_columns in table_configs.items():
                if not table_exists(engine_to_use, table_name):
                    logger.debug("Skipping optional columns for %s (table does not exist)", table_name)
                    continue
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
