from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.models.user import User
from app.deps.auth import get_current_user, get_db
from app.services.paper_engine import evaluate_once

router = APIRouter()

@router.post("/engine/run-once")
def run_once(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Run paper trading engine once for the current user"""
    result = evaluate_once(db, current_user.id)
    return result
