from fastapi import APIRouter, Depends
from app.schemas.user import UserOut
from app.deps.auth import get_current_user
from app.models.user import User

router = APIRouter()

@router.get("/me", response_model=UserOut)
def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information"""
    return current_user
