from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from app.models.user import User
from app.models.risk_limit import InstrumentRiskLimit
from app.schemas.risk_limit import RiskLimitIn, RiskLimitOut
from app.deps.auth import get_current_user, get_db

router = APIRouter()

@router.get("/risk-limits", response_model=RiskLimitOut)
def get_risk_limit(
    instrument_id: int = Query(..., description="Instrument ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get risk limit for an instrument"""
    risk_limit = db.query(InstrumentRiskLimit).filter(
        InstrumentRiskLimit.instrument_id == instrument_id,
        InstrumentRiskLimit.user_id == current_user.id
    ).first()
    
    if not risk_limit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Risk limit not found"
        )
    
    return risk_limit

@router.post("/risk-limits", response_model=RiskLimitOut)
def upsert_risk_limit(
    risk_limit_in: RiskLimitIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create or update risk limit for an instrument"""
    # Check if instrument belongs to user
    from app.models.instrument import Instrument
    instrument = db.query(Instrument).filter(
        Instrument.id == risk_limit_in.instrument_id,
        Instrument.user_id == current_user.id
    ).first()
    
    if not instrument:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument not found"
        )
    
    # Check if risk limit already exists
    existing = db.query(InstrumentRiskLimit).filter(
        InstrumentRiskLimit.instrument_id == risk_limit_in.instrument_id,
        InstrumentRiskLimit.user_id == current_user.id
    ).first()
    
    if existing:
        # Update existing
        existing.max_open_orders = risk_limit_in.max_open_orders
        existing.max_buy_usd = risk_limit_in.max_buy_usd
        existing.allow_margin = risk_limit_in.allow_margin
        existing.max_leverage = risk_limit_in.max_leverage
        existing.preferred_exchange = risk_limit_in.preferred_exchange
        db.commit()
        db.refresh(existing)
        return existing
    else:
        # Create new
        risk_limit = InstrumentRiskLimit(
            user_id=current_user.id,
            instrument_id=risk_limit_in.instrument_id,
            max_open_orders=risk_limit_in.max_open_orders,
            max_buy_usd=risk_limit_in.max_buy_usd,
            allow_margin=risk_limit_in.allow_margin,
            max_leverage=risk_limit_in.max_leverage,
            preferred_exchange=risk_limit_in.preferred_exchange
        )
        db.add(risk_limit)
        db.commit()
        db.refresh(risk_limit)
        return risk_limit
