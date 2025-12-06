"""Database model for dashboard snapshot cache"""
from sqlalchemy import Column, Integer, JSON, DateTime, Text
from sqlalchemy.sql import func
from app.database import Base


class DashboardCache(Base):
    """Model for storing dashboard state snapshots"""
    __tablename__ = "dashboard_cache"
    
    id = Column(Integer, primary_key=True, default=1)  # Always use id=1 for single row
    data = Column(JSON, nullable=False)  # Full dashboard state payload
    last_updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<DashboardCache(id={self.id}, last_updated_at={self.last_updated_at})>"

