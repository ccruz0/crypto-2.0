"""Reports API endpoints for dashboard data integrity and other system reports"""
from fastapi import APIRouter, HTTPException, Header, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from typing import Optional, Dict, Any
import logging
from datetime import datetime
from pydantic import BaseModel

router = APIRouter()
log = logging.getLogger("app.reports")

# In-memory storage for reports (can be replaced with DB table if needed)
_reports_cache: Dict[str, Dict[str, Any]] = {}
_report_secret = None  # Will be set from env var

def get_report_secret() -> str:
    """Get report secret from environment"""
    global _report_secret
    if _report_secret is None:
        import os
        _report_secret = os.getenv("REPORT_SECRET", "dashboard-data-integrity-secret-2024")
    return _report_secret


class DashboardDataIntegrityReport(BaseModel):
    """Pydantic model for dashboard data integrity report"""
    run: Dict[str, Any]
    summary: Dict[str, Any]
    inconsistencies: list
    cursor_prompt: str


@router.post("/reports/dashboard-data-integrity")
async def store_dashboard_data_integrity_report(
    report: DashboardDataIntegrityReport,
    x_report_secret: Optional[str] = Header(None, alias="X-Report-Secret"),
    db: Session = Depends(get_db)
):
    """
    Store dashboard data integrity report from GitHub Actions workflow.
    Protected by X-Report-Secret header.
    """
    secret = get_report_secret()
    
    if x_report_secret != secret:
        log.warning(f"Invalid report secret provided: {x_report_secret}")
        raise HTTPException(status_code=403, detail="Invalid report secret")
    
    try:
        # Store report in cache (keyed by run_id or timestamp)
        run_id = report.run.get("run_id") or f"run-{datetime.now().isoformat()}"
        _reports_cache[run_id] = {
            "report": report.dict(),
            "stored_at": datetime.now().isoformat()
        }
        
        # Keep only the latest 10 reports
        if len(_reports_cache) > 10:
            oldest_key = min(_reports_cache.keys(), key=lambda k: _reports_cache[k]["stored_at"])
            del _reports_cache[oldest_key]
        
        log.info(f"Stored dashboard data integrity report: {run_id}")
        
        return {
            "status": "success",
            "run_id": run_id,
            "stored_at": _reports_cache[run_id]["stored_at"]
        }
    except Exception as e:
        log.error(f"Error storing report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error storing report: {str(e)}")


@router.get("/reports/dashboard-data-integrity/latest")
async def get_latest_dashboard_data_integrity_report(
    db: Session = Depends(get_db)
):
    """
    Get the latest dashboard data integrity report.
    Returns the most recently stored report.
    """
    try:
        if not _reports_cache:
            return {
                "status": "not_found",
                "message": "No reports available yet"
            }
        
        # Get the most recent report
        latest_key = max(_reports_cache.keys(), key=lambda k: _reports_cache[k]["stored_at"])
        latest_report = _reports_cache[latest_key]["report"]
        
        return {
            "status": "success",
            "report": latest_report,
            "stored_at": _reports_cache[latest_key]["stored_at"]
        }
    except Exception as e:
        log.error(f"Error retrieving latest report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error retrieving report: {str(e)}")


@router.get("/reports/dashboard-data-integrity/{run_id}")
async def get_dashboard_data_integrity_report_by_id(
    run_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a specific dashboard data integrity report by run_id.
    """
    try:
        if run_id not in _reports_cache:
            raise HTTPException(status_code=404, detail=f"Report {run_id} not found")
        
        return {
            "status": "success",
            "report": _reports_cache[run_id]["report"],
            "stored_at": _reports_cache[run_id]["stored_at"]
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error retrieving report {run_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error retrieving report: {str(e)}")

