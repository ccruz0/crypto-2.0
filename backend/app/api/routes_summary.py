from fastapi import APIRouter, Depends, HTTPException
from app.deps.auth import get_current_user
from app.services.daily_summary import daily_summary_service
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/summary/send")
def send_manual_summary(current_user = Depends(get_current_user)):
    """Send manual daily summary"""
    try:
        daily_summary_service.send_daily_summary()
        return {"message": "Daily summary sent successfully"}
    except Exception as e:
        logger.error(f"Error sending manual summary: {e}")
        raise HTTPException(status_code=500, detail=f"Error sending summary: {str(e)}")

@router.get("/summary/test")
def test_summary(current_user = Depends(get_current_user)):
    """Test summary generation (without sending)"""
    try:
        portfolio_data = daily_summary_service.get_portfolio_summary()
        return {
            "message": "Summary data generated successfully",
            "data": {
                "total_open_orders": portfolio_data.get('total_open_orders', 0),
                "total_executed_24h": portfolio_data.get('total_executed_24h', 0),
                "has_balance": bool(portfolio_data.get('balance'))
            }
        }
    except Exception as e:
        logger.error(f"Error testing summary: {e}")
        raise HTTPException(status_code=500, detail=f"Error testing summary: {str(e)}")






