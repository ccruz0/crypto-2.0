from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.models.user import User
from app.models.instrument import Instrument
from app.schemas.instrument import InstrumentIn, InstrumentOut
from app.deps.auth import get_current_user, get_db
from typing import List

router = APIRouter()

@router.get("/instruments", response_model=List[InstrumentOut])
def list_instruments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all instruments for the current user"""
    instruments = db.query(Instrument).filter(Instrument.user_id == current_user.id).all()
    return instruments

@router.post("/instruments", response_model=InstrumentOut, status_code=status.HTTP_201_CREATED)
def create_instrument(
    instrument_in: InstrumentIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new instrument for the current user"""
    # Check if symbol already exists for this user
    existing = db.query(Instrument).filter(
        Instrument.user_id == current_user.id,
        Instrument.symbol == instrument_in.symbol
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Symbol already exists for this user"
        )
    
    # Validate venue
    if instrument_in.venue not in ["CRYPTO", "STOCK"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='venue must be "CRYPTO" or "STOCK"'
        )
    
    # Create new instrument
    instrument = Instrument(
        user_id=current_user.id,
        symbol=instrument_in.symbol,
        venue=instrument_in.venue,
        tick_size=instrument_in.tick_size,
        lot_size=instrument_in.lot_size
    )
    
    db.add(instrument)
    db.commit()
    db.refresh(instrument)
    
    return instrument

@router.delete("/instruments/{instrument_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_instrument(
    instrument_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an instrument"""
    instrument = db.query(Instrument).filter(
        Instrument.id == instrument_id,
        Instrument.user_id == current_user.id
    ).first()
    
    if not instrument:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument not found"
        )
    
    db.delete(instrument)
    db.commit()
    
    return None
