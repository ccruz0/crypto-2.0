from sqlalchemy import Column, String, DateTime, Float, Integer, Text
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import json

Base = declarative_base()

class OrderHistory(Base):
    """Model for storing executed order history"""
    __tablename__ = "order_history"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(100), unique=True, index=True)
    client_oid = Column(String(100), index=True)
    instrument_name = Column(String(50), index=True)
    order_type = Column(String(50))
    side = Column(String(10))
    status = Column(String(50))
    quantity = Column(Float)
    price = Column(Float, nullable=True)
    avg_price = Column(Float, nullable=True)
    order_value = Column(Float, nullable=True)
    cumulative_quantity = Column(Float, nullable=True)
    cumulative_value = Column(Float, nullable=True)
    create_time = Column(DateTime, index=True)
    update_time = Column(DateTime)
    # Store raw JSON for additional fields
    raw_data = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        """Convert order to dictionary"""
        result = {
            "order_id": self.order_id,
            "client_oid": self.client_oid,
            "instrument_name": self.instrument_name,
            "order_type": self.order_type,
            "side": self.side,
            "status": self.status,
            "quantity": self.quantity,
            "price": self.price,
            "avg_price": self.avg_price,
            "order_value": self.order_value,
            "cumulative_quantity": self.cumulative_quantity,
            "cumulative_value": self.cumulative_value,
            "create_time": int(self.create_time.timestamp() * 1000) if self.create_time else None,
            "update_time": int(self.update_time.timestamp() * 1000) if self.update_time else None,
        }
        
        # Add any additional fields from raw_data
        if self.raw_data:
            try:
                additional = json.loads(self.raw_data)
                result.update(additional)
            except:
                pass
        
        return result
    
    @staticmethod
    def from_crypto_api(order_data: dict):
        """Create OrderHistory instance from Crypto.com API response"""
        return OrderHistory(
            order_id=str(order_data.get("order_id", "")),
            client_oid=str(order_data.get("client_oid", "")),
            instrument_name=order_data.get("instrument_name", ""),
            order_type=order_data.get("order_type", ""),
            side=order_data.get("side", ""),
            status=order_data.get("status", ""),
            quantity=float(order_data.get("quantity", 0) or 0),
            price=float(order_data.get("limit_price", 0) or 0) if order_data.get("limit_price") else None,
            avg_price=float(order_data.get("avg_price", 0) or 0) if order_data.get("avg_price") else None,
            order_value=float(order_data.get("order_value", 0) or 0) if order_data.get("order_value") else None,
            cumulative_quantity=float(order_data.get("cumulative_quantity", 0) or 0) if order_data.get("cumulative_quantity") else None,
            cumulative_value=float(order_data.get("cumulative_value", 0) or 0) if order_data.get("cumulative_value") else None,
            create_time=datetime.fromtimestamp(order_data.get("create_time", 0) / 1000) if order_data.get("create_time") else datetime.utcnow(),
            update_time=datetime.fromtimestamp(order_data.get("update_time", 0) / 1000) if order_data.get("update_time") else datetime.utcnow(),
            raw_data=json.dumps(order_data)
        )
