from fastapi import FastAPI
 TEMPORARILY DISABLED: Testing if CORS middleware is causing HTTP request hangs
# from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.environment import get_cors_origins, get_environment, is_local, is_aws
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
import os
import logging
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Setup logging configuration early
from app.core.logging_config import setup_logging
setup_logging()

logger = logging.getLogger(__name__)

# DEBUG: Flag to disable heavy middlewares for performance testing
DEBUG_DISABLE_HEAVY_MIDDLEWARES = True

# DEBUG: Flag to disable startup event for performance testing
DEBUG_DISABLE_STARTUP_EVENT = False  # Re-enabled to test individual services

# DEBUG: Flag to disable database import for performance testing
DEBUG_DISABLE_DATABASE_IMPORT = False

# DEBUG: Flags to disable individual background services
DEBUG_DISABLE_EXCHANGE_SYNC = False  # Re-enabled - needed for portfolio data
DEBUG_DISABLE_SIGNAL_MONITOR = False  # Re-enabled - needed for trading alerts
DEBUG_DISABLE_TRADING_SCHEDULER = False  # Re-enabled - needed for automatic trading
DEBUG_DISABLE_VPN_GATE = True  # Keep disabled
DEBUG_DISABLE_TELEGRAM = False  # Enabled for Telegram commands

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
# TEMPORARILY DISABLED: Testing if CORS middleware is causing HTTP request hangs
# cors_origins = get_cors_origins()
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=cors_origins if cors_origins != ["*"] else ["*"],
#     allow_credentials=True,
#     allow_methods=["*"],  # Allow all methods including OPTIONS
#     allow_headers=["*"],
#     expose_headers=["*"],
#     max_age=3600,  # Cache preflight requests for 1 hour
#     )
# logger.info(f"CORS middleware enabled with origins: {cors_origins}")

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
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, init_db)
        
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
                    asyncio.create_task(signal_monitor_service.start())
                    logger.info("✅ Signal monitor service started")
                except Exception as e:
                    logger.error(f"❌ Failed to start signal monitor: {e}", exc_info=True)
            else:
                logger.warning("PERF: Signal monitor service DISABLED for performance testing")
            
            # Buy Index Monitor Service
            try:
                logger.info("🔧 Starting Buy Index Monitor service...")
                from app.services.buy_index_monitor import buy_index_monitor
                asyncio.create_task(buy_index_monitor.run())
                logger.info("✅ Buy Index Monitor service started")
            except Exception as e:
                logger.error(f"❌ Failed to start buy index monitor: {e}", exc_info=True)
            
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
    
    # Schedule background work - won't block startup
    asyncio.create_task(_background_init())
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
