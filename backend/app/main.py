from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.environment import get_environment, is_local, is_aws
from app.api.routes_account import router as account_router
from app.api.routes_internal import router as internal_router
from app.api.routes_orders import router as orders_router
from app.api.routes_instruments import router as instruments_router
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_engine import router as engine_router
from app.api.routes_market import router as market_router
from app.api.routes_signals import router as signals_router
from app.api.routes_summary import router as summary_router
from app.api.routes_manual_trade import router as manual_trade_router
from app.api.routes_test import router as test_router
from app.api.routes_crypto import router as crypto_router
from app.api.routes_import import router as import_router
from app.api.routes_loans import router as loans_router
from app.api.routes_control import router as control_router
from app.routers.config import router as config_router
from app.api.routes_debug import router as debug_router
from app.api.routes_monitoring import router as monitoring_router
from app.api.routes_diag import router as diag_router
from app.api.routes_reports import router as reports_router
import os
import logging
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import os

# Setup logging configuration early
from app.core.logging_config import setup_logging
setup_logging()

logger = logging.getLogger(__name__)

# DEBUG: Flags to disable services (read from environment variables)
# These flags allow disabling services for debugging/performance testing
# Set to "true" (case-insensitive) to disable, "false" to enable
def _get_bool_env(env_var: str, default: bool = False) -> bool:
    """Get boolean from environment variable"""
    value = os.getenv(env_var, "").lower()
    return value in ("true", "1", "yes", "on")

DEBUG_DISABLE_HEAVY_MIDDLEWARES = _get_bool_env("DEBUG_DISABLE_HEAVY_MIDDLEWARES", True)
DEBUG_DISABLE_STARTUP_EVENT = _get_bool_env("DEBUG_DISABLE_STARTUP_EVENT", False)
DEBUG_DISABLE_DATABASE_IMPORT = _get_bool_env("DEBUG_DISABLE_DATABASE_IMPORT", False)
DEBUG_DISABLE_EXCHANGE_SYNC = _get_bool_env("DEBUG_DISABLE_EXCHANGE_SYNC", False)
DEBUG_DISABLE_SIGNAL_MONITOR = _get_bool_env("DEBUG_DISABLE_SIGNAL_MONITOR", False)
DEBUG_DISABLE_TRADING_SCHEDULER = _get_bool_env("DEBUG_DISABLE_TRADING_SCHEDULER", False)
DEBUG_DISABLE_VPN_GATE = _get_bool_env("DEBUG_DISABLE_VPN_GATE", True)
DEBUG_DISABLE_TELEGRAM = _get_bool_env("DEBUG_DISABLE_TELEGRAM", False)

# Performance timing middleware
class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0 = time.perf_counter()
        logger.info(f"PERF: Request started - {request.method} {request.url.path}")
        
        response = await call_next(request)
        
        t1 = time.perf_counter()
        elapsed_ms = (t1 - t0) * 1000
        logger.info(f"PERF: Request completed - {request.method} {request.url.path} - {elapsed_ms:.2f}ms")
        
        return response

# Lazy import database to avoid connection failure on startup
engine = None
Base = None
ensure_optional_columns = None
if not DEBUG_DISABLE_DATABASE_IMPORT:
    try:
        from app.database import engine, Base, ensure_optional_columns
    except ImportError:
        from app.database import engine, Base
        ensure_optional_columns = None
    except Exception as e:
        logger.warning(f"Database import failed: {e}. Running without database.")
else:
    logger.warning("PERF: Database import DISABLED for performance testing")

from app.services.scheduler import trading_scheduler

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.40.0",
    description="Automated Trading Platform API"
)

# Performance timing middleware - add FIRST to measure everything
# TEMPORARILY DISABLED: Testing if this middleware is causing HTTP request hangs
# app.add_middleware(TimingMiddleware)

# CORS middleware - ALWAYS enabled for browser requests (required for frontend)
# This must be added BEFORE routers to handle OPTIONS preflight requests
from fastapi.middleware.cors import CORSMiddleware
cors_origins = [
    "http://localhost:3000",
    "http://localhost:3001", 
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "https://dashboard.hilovivo.com",
    "https://www.dashboard.hilovivo.com"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods including OPTIONS
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,  # Cache preflight requests for 1 hour
    )

# Build fingerprint middleware - adds commit/build time and DB fingerprint to all responses
class BuildFingerprintMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Add build fingerprint headers
        git_sha = os.getenv("ATP_GIT_SHA", "unknown")
        build_time = os.getenv("ATP_BUILD_TIME", "unknown")
        response.headers["X-ATP-Backend-Commit"] = git_sha
        response.headers["X-ATP-Backend-BuildTime"] = build_time
        
        # Add DB fingerprint headers (for verification scripts to match DB)
        import hashlib
        from urllib.parse import urlparse, urlunparse
        database_url = os.getenv("DATABASE_URL", "")
        if database_url:
            try:
                parsed = urlparse(database_url)
                # Extract host and database name
                db_host = parsed.hostname or "unknown"
                db_name = parsed.path.lstrip("/") if parsed.path else "unknown"
                
                # Create hash of DATABASE_URL with password stripped (never include password)
                safe_url = urlunparse(parsed._replace(netloc=f"{parsed.username or ''}@{parsed.hostname or ''}:{parsed.port or ''}"))
                db_hash = hashlib.sha256(safe_url.encode()).hexdigest()[:10]
                
                response.headers["X-ATP-DB-Host"] = db_host
                response.headers["X-ATP-DB-Name"] = db_name
                response.headers["X-ATP-DB-Hash"] = db_hash
            except Exception:
                response.headers["X-ATP-DB-Host"] = "unknown"
                response.headers["X-ATP-DB-Name"] = "unknown"
                response.headers["X-ATP-DB-Hash"] = "unknown"
        else:
            response.headers["X-ATP-DB-Host"] = "unknown"
            response.headers["X-ATP-DB-Name"] = "unknown"
            response.headers["X-ATP-DB-Hash"] = "unknown"
        
        return response

app.add_middleware(BuildFingerprintMiddleware)
logger.info(f"CORS middleware enabled with origins: {cors_origins}")

# Startup validation and database initialization
@app.on_event("startup")
async def startup_event():
    """Startup event - must complete immediately to allow requests"""
    # Set backend restart time for monitoring
    try:
        from app.api.routes_monitoring import set_backend_restart_time
        set_backend_restart_time()
    except Exception:
        pass  # Ignore if monitoring module not available
    
    # Verify critical scripts exist (if PRINT_FINGERPRINTS_ON_START is set)
    if os.getenv("PRINT_FINGERPRINTS_ON_START") == "1":
        import pathlib
        scripts_path = pathlib.Path("/app/scripts/print_api_fingerprints.py")
        if scripts_path.exists():
            logger.info(f"✅ Verified: {scripts_path} exists")
        else:
            logger.warning(f"⚠️  Warning: {scripts_path} not found in container")
    
    if DEBUG_DISABLE_STARTUP_EVENT:
        logger.warning("PERF: Startup event DISABLED for performance testing")
        return
    
    import asyncio
    t0 = time.perf_counter()
    logger.info("PERF: Startup event started")
    
    # Schedule ALL background work without blocking - fire and forget
    async def _background_init():
        """All background initialization - runs after startup completes"""
        try:
            # VPN Gate monitor
            if not DEBUG_DISABLE_VPN_GATE:
                try:
                    from app.utils.vpn_gate import monitor
                    vpn_logger = logging.getLogger("app.vpn_gate")
                    if os.getenv("VPN_GATE_BACKGROUND", "true").lower() == "true":
                        asyncio.create_task(monitor(vpn_logger))
                        vpn_logger.info("vpn_gate: background monitor started")
                except Exception as e:
                    logger.warning(f"vpn_gate: error: {e}")
            else:
                logger.warning("PERF: VPN Gate monitor DISABLED for performance testing")
            
            # Database initialization in thread
            if engine and Base:
                def init_db():
                    try:
                        Base.metadata.create_all(bind=engine)
                        if ensure_optional_columns:
                            ensure_optional_columns(engine)
                        logger.info("Database tables initialized (including optional columns)")
                    except Exception as e:
                        logger.warning(f"Database initialization failed: {e}")

                # Ensure DB initialization completes before scheduling other services.
                # Run in default executor but await completion so dependent services see the DB.
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, init_db)
                logger.info("Database initialization completed")
            
            # Eagerly initialize TelegramNotifier to ensure TELEGRAM_STARTUP log appears
            # This triggers __init__ which logs [TELEGRAM_STARTUP] exactly once
            try:
                from app.services.telegram_notifier import telegram_notifier
                # Access the instance to ensure initialization (already instantiated at module level)
                # This is a no-op but ensures the module is imported and __init__ has run
                _ = telegram_notifier.enabled  # Access attribute to ensure initialization
                logger.debug("TelegramNotifier initialized (TELEGRAM_STARTUP log should appear above)")
            except Exception as e:
                logger.warning(f"Failed to initialize TelegramNotifier: {e}")
            
            # Telegram startup diagnostics (run once on startup)
            try:
                from app.services.telegram_commands import _run_startup_diagnostics
                logger.info("🔧 Running Telegram startup diagnostics...")
                await loop.run_in_executor(None, _run_startup_diagnostics)
                logger.info("✅ Telegram startup diagnostics completed")
            except Exception as e:
                logger.error(f"❌ Telegram startup diagnostics failed: {e}", exc_info=True)
        
            # Services            
            if not DEBUG_DISABLE_TRADING_SCHEDULER:
                try:
                    logger.info("🔧 Starting Trading scheduler...")
                    # Start scheduler in background without blocking - fire and forget
                    # Use create_task to avoid blocking startup event
                    async def start_scheduler():
                        try:
                            await trading_scheduler.start()
                            logger.info("✅ Trading scheduler started")
                        except Exception as e:
                            logger.error(f"❌ Failed to start trading scheduler: {e}", exc_info=True)
                    asyncio.create_task(start_scheduler())
                    logger.info("✅ Trading scheduler start() called (non-blocking)")
                except Exception as e:
                    logger.error(f"❌ Failed to start trading scheduler: {e}", exc_info=True)
            else:
                logger.warning("PERF: Trading scheduler DISABLED for performance testing")
            
            if not DEBUG_DISABLE_EXCHANGE_SYNC:
                try:
                    logger.info("🔧 Starting Exchange sync service...")
                    from app.services.exchange_sync import exchange_sync_service
                    # Start exchange_sync service (has built-in delay to avoid blocking startup)
                    asyncio.create_task(exchange_sync_service.start())
                    logger.info("✅ Exchange sync service started (will delay first sync by 15s)")
                except Exception as e:
                    logger.error(f"❌ Failed to start exchange sync: {e}", exc_info=True)
            else:
                logger.warning("PERF: Exchange sync service DISABLED for performance testing")
            
            if not DEBUG_DISABLE_SIGNAL_MONITOR:
                try:
                    logger.info("🔧 Starting Signal monitor service...")
                    from app.services.signal_monitor import signal_monitor_service
                    loop = asyncio.get_running_loop()
                    signal_monitor_service.start_background(loop)
                    logger.info("✅ Signal monitor service start() scheduled")
                except Exception as e:
                    logger.error(f"❌ Failed to start signal monitor: {e}", exc_info=True)
            else:
                logger.warning("PERF: Signal monitor service DISABLED for performance testing")
            
            # Buy Index Monitor Service - DISABLED
            # try:
            #     logger.info("🔧 Starting Buy Index Monitor service...")
            #     from app.services.buy_index_monitor import buy_index_monitor
            #     asyncio.create_task(buy_index_monitor.run())
            #     logger.info("✅ Buy Index Monitor service started")
            # except Exception as e:
            #     logger.error(f"❌ Failed to start buy index monitor: {e}", exc_info=True)
            logger.info("⚠️ Buy Index Monitor service is DISABLED")
            
            if not DEBUG_DISABLE_TELEGRAM:
                try:
                    from app.services.telegram_commands import setup_bot_commands
                    loop = asyncio.get_event_loop()
                    loop.run_in_executor(None, setup_bot_commands)
                except Exception as e:
                    logger.warning(f"Failed to setup Telegram: {e}")
            else:
                logger.warning("PERF: Telegram commands DISABLED for performance testing")
        except Exception as e:
            logger.error(f"Background init error: {e}", exc_info=True)
    
    # Ensure watchlist is never empty and sync with portfolio symbols
    async def _ensure_watchlist_not_empty():
        """Ensure watchlist has at least some items based on portfolio and sync missing portfolio coins"""
        # Bug 2 Fix: Ensure db session is always closed, even if exception occurs before inner try
        db = None
        try:
            from app.database import SessionLocal
            from app.models.watchlist import WatchlistItem
            from app.services.portfolio_cache import get_portfolio_summary
            
            db = SessionLocal()
            try:
                # Get portfolio symbols
                portfolio_symbols = set()
                try:
                    portfolio = get_portfolio_summary(db)
                    assets = portfolio.get("assets", [])
                    # Extract symbols from portfolio (exclude stablecoins)
                    for asset in assets:
                        symbol = asset.get("coin", "").upper()
                        if symbol and symbol not in ["USD", "USDT", "USDC", "EUR"]:
                            portfolio_symbols.add(symbol)
                except Exception as portfolio_err:
                    logger.warning(f"Error getting portfolio for watchlist sync: {portfolio_err}")
                
                # Get existing watchlist symbols
                existing_items = db.query(WatchlistItem).all()
                existing_symbols = {item.symbol.upper() for item in existing_items if not item.is_deleted}
                
                # Check if watchlist is empty
                count = len(existing_symbols)
                if count == 0:
                    logger.warning("Watchlist is empty - initializing with portfolio symbols...")
                    
                    # Default symbols to add if portfolio is also empty
                    default_symbols = ["BTC_USDT", "ETH_USDT", "SOL_USD", "ALGO", "DOT_USD", 
                                     "AAVE_USD", "XRP", "DOGE_USD", "DGB_USD", "BONK_USD"]
                    
                    symbols_to_add = []
                    if portfolio_symbols:
                        # Add all portfolio symbols
                        symbols_to_add.extend(list(portfolio_symbols))
                    
                    # Add default symbols if we don't have enough from portfolio
                    for symbol in default_symbols:
                        if symbol not in symbols_to_add and len(symbols_to_add) < 10:
                            symbols_to_add.append(symbol)
                    
                    # Create watchlist items
                    items_created = 0
                    processed_symbols = []  # Track symbols that were actually created or restored
                    for symbol in symbols_to_add[:10]:  # Limit to 10 items for initial load
                        # Check if item already exists (including deleted)
                        existing = db.query(WatchlistItem).filter(
                            WatchlistItem.symbol == symbol,
                            WatchlistItem.exchange == "CRYPTO_COM"
                        ).first()
                        
                        if existing:
                            # Restore deleted item
                            if existing.is_deleted:
                                existing.is_deleted = False
                                existing.trade_enabled = False
                                existing.alert_enabled = False
                                items_created += 1
                                processed_symbols.append(symbol)
                        else:
                            # Create new item
                            new_item = WatchlistItem(
                                symbol=symbol,
                                exchange="CRYPTO_COM",
                                is_deleted=False,
                                trade_enabled=False,
                                alert_enabled=False,
                                sl_tp_mode="conservative"
                            )
                            db.add(new_item)
                            items_created += 1
                            processed_symbols.append(symbol)
                    
                    if items_created > 0:
                        db.commit()
                        logger.info(f"✅ Initialized watchlist with {items_created} items: {', '.join(processed_symbols)}")
                    else:
                        logger.info("Watchlist initialization skipped - no new items needed")
                else:
                    # Watchlist not empty - sync missing portfolio coins
                    missing_symbols = portfolio_symbols - existing_symbols
                    if missing_symbols:
                        items_added = 0
                        processed_symbols = []  # Track symbols that were actually created or restored
                        for symbol in missing_symbols:
                            # Check if item exists but is deleted
                            existing = db.query(WatchlistItem).filter(
                                WatchlistItem.symbol == symbol,
                                WatchlistItem.exchange == "CRYPTO_COM"
                            ).first()
                            
                            if existing:
                                # Restore deleted item
                                if existing.is_deleted:
                                    existing.is_deleted = False
                                    existing.trade_enabled = False
                                    existing.alert_enabled = False
                                    items_added += 1
                                    processed_symbols.append(symbol)
                            else:
                                # Create new item
                                new_item = WatchlistItem(
                                    symbol=symbol,
                                    exchange="CRYPTO_COM",
                                    is_deleted=False,
                                    trade_enabled=False,
                                    alert_enabled=False,
                                    sl_tp_mode="conservative"
                                )
                                db.add(new_item)
                                items_added += 1
                                processed_symbols.append(symbol)
                        
                        if items_added > 0:
                            db.commit()
                            logger.info(f"✅ Synced {items_added} missing portfolio coins to watchlist: {', '.join(sorted(processed_symbols))}")
                    else:
                        logger.debug(f"Watchlist already has {count} items and all portfolio coins are present - no sync needed")
            except Exception as inner_e:
                logger.error(f"Error in watchlist sync inner block: {inner_e}", exc_info=True)
                if db:
                    db.rollback()
        except Exception as e:
            logger.error(f"Error ensuring watchlist is not empty: {e}", exc_info=True)
            if db:
                db.rollback()
        finally:
            # Bug 2 Fix: Ensure db session is always closed, even if exception occurs anywhere
            # This handles both inner try exceptions and outer try exceptions (imports, SessionLocal)
            if db:
                try:
                    db.close()
                except Exception:
                    pass  # Ignore errors during cleanup
    
        # Schedule background work - won't block startup
    # CRITICAL FIX: Start background services and signal_monitor directly
    logger.info("📋 Starting background services...")
    try:
        # Start _background_init() which starts all services
        background_task = asyncio.create_task(_background_init())
        await asyncio.sleep(0.3)
        logger.info(f"✅ _background_init() task created: done={background_task.done()}")
        
        # NOTE: Signal monitor is already started in _background_init(), no need to start twice
    except Exception as e:
        logger.error(f"❌ Failed to start background services: {e}", exc_info=True)
    
    # Schedule watchlist initialization in background (with delay to allow DB to be ready) in background (with delay to allow DB to be ready)
    async def _delayed_watchlist_init():
        await asyncio.sleep(10)  # Wait 10 seconds for DB and services to be ready
        await _ensure_watchlist_not_empty()
    asyncio.create_task(_delayed_watchlist_init())
    
    t1 = time.perf_counter()
    elapsed_ms = (t1 - t0) * 1000
    logger.info(f"PERF: Startup event completed - server ready for requests - {elapsed_ms:.2f}ms")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown"""
    try:
        from app.services.websocket_manager import stop_websocket
        await stop_websocket()
        logger.info("WebSocket stopped on shutdown")
    except Exception as e:
        logger.error(f"Error stopping WebSocket: {e}")

# Define simple endpoints BEFORE routers to ensure they're accessible
@app.get("/__ping")
def __ping():
    return {"ok": True}

@app.get("/test")
def test():
    """Simple test endpoint without dependencies"""
    return {"status": "ok", "message": "Backend is responding"}

@app.get("/route_fix_test")
def route_fix_test():
    """Routing fix test endpoint - debug hanging paths"""
    return {"status": "ok", "source": "route_fix_test"}

@app.get("/ping_fast")
def ping_fast():
    """Ultra-fast ping endpoint - minimal processing"""
    return {"status": "ok", "source": "ping_fast"}

@app.get("/")
def root():
    """Root endpoint - simplified to avoid blocking"""
    return {
        "message": "Automated Trading Platform API",
        "version": "0.40.0",
        "status": "running"
    }

@app.get("/health")
def health():
    # Simplified health endpoint - return immediately without blocking
    t0 = time.perf_counter()
    result = {"status": "ok"}
    t1 = time.perf_counter()
    elapsed_ms = (t1 - t0) * 1000
    logger.info(f"PERF: /health handler executed in {elapsed_ms:.2f}ms")
    return result

# Alias health under /api for reverse-proxy setups that expect /api/health
@app.get("/api/health")
def api_health():
    # Reuse same simple response as /health
    t0 = time.perf_counter()
    result = {"status": "ok", "path": "/api/health"}
    t1 = time.perf_counter()
    elapsed_ms = (t1 - t0) * 1000
    logger.info(f"PERF: /api/health handler executed in {elapsed_ms:.2f}ms")
    return result

# Include routers AFTER simple endpoints
app.include_router(account_router, prefix="/api", tags=["account"])
app.include_router(internal_router, prefix="/api", tags=["internal"])
app.include_router(orders_router, prefix="/api", tags=["orders"])
app.include_router(instruments_router, prefix="/api", tags=["instruments"])
app.include_router(dashboard_router, prefix="/api", tags=["dashboard"])
app.include_router(engine_router, prefix="/api", tags=["engine"])
app.include_router(market_router, prefix="/api", tags=["market"])
app.include_router(signals_router, prefix="/api", tags=["signals"])
app.include_router(summary_router, prefix="/api", tags=["summary"])
app.include_router(manual_trade_router, prefix="/api", tags=["manual-trade"])
app.include_router(test_router, prefix="/api", tags=["test"])
app.include_router(crypto_router, prefix="/api", tags=["crypto"])
app.include_router(import_router, prefix="/api", tags=["import"])
app.include_router(loans_router, prefix="/api", tags=["loans"])
app.include_router(control_router, prefix="/api", tags=["control"])
app.include_router(monitoring_router, prefix="/api", tags=["monitoring"])
app.include_router(config_router, tags=["config"])
app.include_router(debug_router, prefix="/api", tags=["debug"])
app.include_router(diag_router, prefix="/api", tags=["diagnostics"])
app.include_router(reports_router, prefix="/api", tags=["reports"])
