from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session
from app.models.db import SessionLocal
from app.models.user import User
import hashlib

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(x_api_key: str = Header(..., alias="X-API-Key")) -> User:
    """Get current user from API key header"""
    # Calculate SHA256 hash of the API key
    api_key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    
    # Search for user in database
    db = next(get_db())
    user = db.query(User).filter(User.api_key_hash == api_key_hash).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    return user
