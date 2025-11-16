#!/usr/bin/env python3

from fastapi import FastAPI, Query
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from simple_price_fetcher import price_fetcher

app = FastAPI()

@app.get("/test-price")
def test_price(symbol: str = Query(..., description="Trading symbol")):
    """Test endpoint to check price fetching"""
    try:
        price_result = price_fetcher.get_price(symbol)
        return {
            "symbol": symbol,
            "price": price_result.price,
            "source": price_result.source,
            "success": price_result.success,
            "error": price_result.error
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/health")
def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)

