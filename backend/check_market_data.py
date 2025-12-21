#!/usr/bin/env python3
"""Check MarketData for symbols"""
from app.database import SessionLocal
from app.models.market_price import MarketData

db = SessionLocal()
symbols = ['ALGO_USDT', 'BTC_USDT', 'SOL_USDT', 'DOGE_USDT']

for symbol in symbols:
    md = db.query(MarketData).filter(MarketData.symbol == symbol).first()
    if md:
        print(f"{symbol}: price={md.price}, rsi={md.rsi}, ma50={md.ma50}, ema10={md.ema10}, ma200={md.ma200}")
    else:
        print(f"{symbol}: Not found in MarketData")

db.close()




