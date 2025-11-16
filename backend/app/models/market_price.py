"""Database model for current market prices"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Index
from sqlalchemy.sql import func
from app.database import Base


class MarketPrice(Base):
    """Model for storing current market prices for all symbols"""
    __tablename__ = "market_prices"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), nullable=False, unique=True, index=True)  # e.g., "ETH_USDT"
    exchange = Column(String(50), default="CRYPTO_COM")
    price = Column(Float, nullable=False)
    source = Column(String(50), nullable=True)  # e.g., "crypto_com", "binance", "coingecko"
    volume_24h = Column(Float, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True)
    
    # Index on symbol for fast lookups
    __table_args__ = (
        Index('ix_market_prices_symbol_exchange', 'symbol', 'exchange'),
    )
    
    def __repr__(self):
        return f"<MarketPrice(symbol={self.symbol}, price={self.price}, updated_at={self.updated_at})>"


class MarketData(Base):
    """Model for storing technical indicators and market data for all symbols"""
    __tablename__ = "market_data"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), nullable=False, unique=True, index=True)  # e.g., "ETH_USDT"
    exchange = Column(String(50), default="CRYPTO_COM")
    
    # Technical indicators
    price = Column(Float, nullable=False)
    rsi = Column(Float, nullable=True)
    atr = Column(Float, nullable=True)
    ma50 = Column(Float, nullable=True)
    ma200 = Column(Float, nullable=True)
    ema10 = Column(Float, nullable=True)
    ma10w = Column(Float, nullable=True)
    
    # Volume data
    volume_24h = Column(Float, nullable=True)
    current_volume = Column(Float, nullable=True)  # Volume of the last period (1h), used for ratio calculation
    avg_volume = Column(Float, nullable=True)
    volume_ratio = Column(Float, nullable=True)
    
    # Resistance levels
    res_up = Column(Float, nullable=True)
    res_down = Column(Float, nullable=True)
    
    # Metadata
    source = Column(String(50), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True)
    
    # Index on symbol for fast lookups
    __table_args__ = (
        Index('ix_market_data_symbol_exchange', 'symbol', 'exchange'),
    )
    
    def __repr__(self):
        return f"<MarketData(symbol={self.symbol}, price={self.price}, rsi={self.rsi}, updated_at={self.updated_at})>"

