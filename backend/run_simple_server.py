#!/usr/bin/env python3
"""
Simple FastAPI server for local testing
Only loads order history endpoints without PostgreSQL dependencies
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="Trading Platform - Local Test")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import only order-related endpoints
from app.api import routes_orders, routes_import, routes_market, routes_dashboard_simple, routes_price
from app.api import routes_signals_fixed as routes_signals
from app.routers import config

app.include_router(routes_orders.router, prefix="/api", tags=["orders"])
app.include_router(routes_import.router, prefix="/api", tags=["import"])
app.include_router(routes_market.router, prefix="/api", tags=["market"])
app.include_router(routes_signals.router, prefix="/api", tags=["signals"])
app.include_router(routes_dashboard_simple.router, prefix="/api", tags=["dashboard"])
app.include_router(routes_price.router, prefix="/api", tags=["price"])
app.include_router(config.router, tags=["config"])

@app.get("/health")
def health():
    return {"status": "healthy", "environment": "local"}

@app.get("/api/test-config")
def test_config():
    return {"message": "Config router is working"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
