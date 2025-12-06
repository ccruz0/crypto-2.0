"""Loan management API endpoints"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.deps.auth import get_current_user
from app.models.portfolio_loan import PortfolioLoan
from app.services.portfolio_cache import get_crypto_prices

router = APIRouter()
log = logging.getLogger("app.loans")


class LoanInput(BaseModel):
    currency: str
    borrowed_amount: float
    borrowed_usd_value: Optional[float] = None
    interest_rate: Optional[float] = None
    notes: Optional[str] = None


class LoanResponse(BaseModel):
    id: int
    currency: str
    borrowed_amount: float
    borrowed_usd_value: float
    interest_rate: Optional[float]
    notes: Optional[str]
    is_active: bool


@router.get("/loans")
def get_loans(db: Session = Depends(get_db)) -> List[LoanResponse]:
    """Get all active loans"""
    try:
        loans = db.query(PortfolioLoan).filter(
            PortfolioLoan.is_active == True
        ).all()
        
        return [
            LoanResponse(
                id=loan.id,
                currency=loan.currency,
                borrowed_amount=float(loan.borrowed_amount),
                borrowed_usd_value=float(loan.borrowed_usd_value),
                interest_rate=float(loan.interest_rate) if loan.interest_rate else None,
                notes=loan.notes,
                is_active=loan.is_active
            )
            for loan in loans
        ]
    except Exception as e:
        log.error(f"Error getting loans: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/loans")
def add_loan(
    loan: LoanInput = Body(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
) -> LoanResponse:
    """Add a new loan"""
    try:
        # If USD value not provided, calculate it from current prices
        borrowed_usd_value = loan.borrowed_usd_value
        if borrowed_usd_value is None or borrowed_usd_value == 0:
            currency = loan.currency.upper()
            if currency in ["USD", "USDT", "USDC"]:
                borrowed_usd_value = loan.borrowed_amount
            else:
                prices = get_crypto_prices()
                if currency in prices:
                    borrowed_usd_value = loan.borrowed_amount * prices[currency]
                    log.info(f"Calculated USD value for {currency} loan: {loan.borrowed_amount} × ${prices[currency]} = ${borrowed_usd_value}")
                else:
                    log.warning(f"No price found for {currency}, using 0 USD value")
                    borrowed_usd_value = 0
        
        new_loan = PortfolioLoan(
            currency=loan.currency.upper(),
            borrowed_amount=loan.borrowed_amount,
            borrowed_usd_value=borrowed_usd_value,
            interest_rate=loan.interest_rate,
            notes=loan.notes,
            is_active=True
        )
        
        db.add(new_loan)
        db.commit()
        db.refresh(new_loan)
        
        log.info(f"Added new loan: {loan.currency} ${borrowed_usd_value}")
        
        return LoanResponse(
            id=new_loan.id,
            currency=new_loan.currency,
            borrowed_amount=float(new_loan.borrowed_amount),
            borrowed_usd_value=float(new_loan.borrowed_usd_value),
            interest_rate=float(new_loan.interest_rate) if new_loan.interest_rate else None,
            notes=new_loan.notes,
            is_active=new_loan.is_active
        )
    except Exception as e:
        log.error(f"Error adding loan: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/loans/{loan_id}")
def update_loan(
    loan_id: int,
    loan: LoanInput = Body(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
) -> LoanResponse:
    """Update an existing loan"""
    try:
        existing_loan = db.query(PortfolioLoan).filter(
            PortfolioLoan.id == loan_id
        ).first()
        
        if not existing_loan:
            raise HTTPException(status_code=404, detail=f"Loan {loan_id} not found")
        
        # Update fields
        existing_loan.currency = loan.currency.upper()
        existing_loan.borrowed_amount = loan.borrowed_amount
        
        # If USD value not provided, calculate it
        if loan.borrowed_usd_value is not None:
            existing_loan.borrowed_usd_value = loan.borrowed_usd_value
        else:
            currency = loan.currency.upper()
            if currency in ["USD", "USDT", "USDC"]:
                existing_loan.borrowed_usd_value = loan.borrowed_amount
            else:
                prices = get_crypto_prices()
                if currency in prices:
                    existing_loan.borrowed_usd_value = loan.borrowed_amount * prices[currency]
                else:
                    existing_loan.borrowed_usd_value = 0
        
        if loan.interest_rate is not None:
            existing_loan.interest_rate = loan.interest_rate
        if loan.notes is not None:
            existing_loan.notes = loan.notes
        
        db.commit()
        db.refresh(existing_loan)
        
        log.info(f"Updated loan {loan_id}: {existing_loan.currency} ${existing_loan.borrowed_usd_value}")
        
        return LoanResponse(
            id=existing_loan.id,
            currency=existing_loan.currency,
            borrowed_amount=float(existing_loan.borrowed_amount),
            borrowed_usd_value=float(existing_loan.borrowed_usd_value),
            interest_rate=float(existing_loan.interest_rate) if existing_loan.interest_rate else None,
            notes=existing_loan.notes,
            is_active=existing_loan.is_active
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating loan {loan_id}: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/loans/{loan_id}")
def delete_loan(
    loan_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Delete (deactivate) a loan"""
    try:
        loan = db.query(PortfolioLoan).filter(
            PortfolioLoan.id == loan_id
        ).first()
        
        if not loan:
            raise HTTPException(status_code=404, detail=f"Loan {loan_id} not found")
        
        # Soft delete by marking as inactive
        loan.is_active = False
        db.commit()
        
        log.info(f"Deleted loan {loan_id}: {loan.currency}")
        
        return {"ok": True, "message": f"Loan {loan_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error deleting loan {loan_id}: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

