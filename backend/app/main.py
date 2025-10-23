from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import hashlib
import logging
from app.models.db import Base, engine, SessionLocal
from app.models.user import User
from app.models.instrument import Instrument
from app.models.risk_limit import InstrumentRiskLimit
from app.models.order import Order
from app.models.position import Position
from app.models.watchlist import Watchlist
from app.api.routes_auth import router as auth_router
from app.api.routes_instruments import router as instruments_router
from app.api.routes_risk import router as risk_router
from app.api.routes_market import router as market_router
from app.api.routes_account import router as account_router
from app.api.routes_orders import router as orders_router
from app.api.routes_engine import router as engine_router
from app.api.routes_dashboard import router as dashboard_router

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Automated Trading Platform")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    """Create tables and demo user on startup"""
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    # Create demo user
    db = SessionLocal()
    try:
        # Check if demo user already exists
        demo_user = db.query(User).filter(User.email == "demo@local").first()
        if not demo_user:
            # Create demo user with api_key="demo-key"
            api_key_hash = hashlib.sha256("demo-key".encode()).hexdigest()
            demo_user = User(
                email="demo@local",
                api_key_hash=api_key_hash
            )
            db.add(demo_user)
            db.commit()
            print("Demo user created successfully")
    finally:
        db.close()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"message": "Automated Trading Platform API", "database": os.getenv("POSTGRES_DB", "not_set")}

# Include routers
app.include_router(auth_router, prefix="/api", tags=["auth"])
app.include_router(instruments_router, prefix="/api", tags=["instruments"])
app.include_router(risk_router, prefix="/api", tags=["risk"])
app.include_router(market_router, prefix="/api", tags=["market"])
app.include_router(engine_router, prefix="/api", tags=["engine"])
app.include_router(dashboard_router, prefix="/api", tags=["dashboard"])
app.include_router(account_router, prefix="/api", tags=["account"])
app.include_router(orders_router, prefix="/api", tags=["orders"])
