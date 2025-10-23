from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Boolean, Text
from sqlalchemy.sql import func
from datetime import datetime
from app.models.db import Base

class Watchlist(Base):
    __tablename__ = "watchlist"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    symbol = Column(String, nullable=False)
    exchange = Column(String, default="BINANCE")
    buy_target = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    order_status = Column(String, default="WAIT")
    order_date = Column(DateTime, nullable=True)
    purchase_price = Column(Float, nullable=True)
    quantity = Column(Float, nullable=True)
    sold = Column(Boolean, default=False)
    sell_price = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
