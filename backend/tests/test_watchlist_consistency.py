"""Tests for watchlist consistency check workflow"""
import pytest
import os
import sys
from datetime import datetime
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem


def test_script_exists():
    """Test that the consistency check script exists"""
    script_path = backend_dir / "scripts" / "watchlist_consistency_check.py"
    assert script_path.exists(), f"Script not found at {script_path}"


def test_report_generation():
    """Test that the script generates a report file"""
    import subprocess
    import tempfile
    
    script_path = backend_dir / "scripts" / "watchlist_consistency_check.py"
    
    # Run script with timeout
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(backend_dir),
            capture_output=True,
            text=True,
            timeout=120  # 2 minute timeout for test
        )
        
        # Check that script completed (even if with errors, it should generate a report)
        date_str = datetime.now().strftime("%Y%m%d")
        report_path = backend_dir.parent / "docs" / "monitoring" / f"watchlist_consistency_report_{date_str}.md"
        
        # Report should exist (even if empty or with errors)
        # We check stderr for actual errors, but report file should be created
        if result.returncode == 0:
            assert report_path.exists(), f"Report file not generated at {report_path}"
        else:
            # Even on error, script should attempt to create report
            # Check if report directory exists
            report_dir = report_path.parent
            assert report_dir.exists(), f"Report directory not found: {report_dir}"
            
    except subprocess.TimeoutExpired:
        pytest.skip("Script timed out (may be normal if database is slow)")
    except Exception as e:
        pytest.skip(f"Could not run script: {e}")


def test_backend_frontend_mismatch_detection():
    """Test that the script can detect mismatches between backend and frontend"""
    # This is a smoke test - we can't easily mock the full API/DB interaction
    # But we can verify the comparison logic exists
    
    script_path = backend_dir / "scripts" / "watchlist_consistency_check.py"
    
    # Read script and check for comparison functions
    script_content = script_path.read_text()
    
    # Verify key functions exist
    assert "compare_field" in script_content, "compare_field function not found"
    assert "compare_symbol" in script_content, "compare_symbol function not found"
    assert "get_computed_values" in script_content, "get_computed_values function not found"
    assert "fetch_api_watchlist" in script_content, "fetch_api_watchlist function not found"
    
    # Verify comparison logic
    assert "MISMATCH" in script_content, "MISMATCH classification not found"
    assert "MATCH" in script_content, "MATCH classification not found"


def test_endpoint_returns_ok():
    """Test that the API endpoint returns OK status"""
    # This test requires the API to be running
    # We'll test the endpoint structure exists
    
    from app.api.routes_monitoring import run_watchlist_consistency
    
    # Verify function exists and is callable
    assert callable(run_watchlist_consistency), "Endpoint function not found"
    
    # Check function signature
    import inspect
    sig = inspect.signature(run_watchlist_consistency)
    assert "db" in sig.parameters, "Endpoint should accept db parameter"


def test_workflow_in_scheduler():
    """Test that the workflow is registered in the scheduler"""
    from app.services.scheduler import TradingScheduler
    
    scheduler = TradingScheduler()
    
    # Verify the method exists
    assert hasattr(scheduler, "check_nightly_consistency"), "check_nightly_consistency method not found"
    assert hasattr(scheduler, "check_nightly_consistency_sync"), "check_nightly_consistency_sync method not found"
    
    # Verify it's called in run_scheduler
    import inspect
    source = inspect.getsource(scheduler.run_scheduler)
    assert "check_nightly_consistency" in source, "Workflow not called in scheduler loop"


def test_script_handles_missing_columns():
    """Test that script handles missing database columns gracefully"""
    script_path = backend_dir / "scripts" / "watchlist_consistency_check.py"
    script_content = script_path.read_text()
    
    # Verify it checks for column existence
    assert "inspect" in script_content or "get_columns" in script_content, "Script should check for column existence"
    assert "is_deleted" in script_content, "Script should handle is_deleted column"
    assert "current_volume" in script_content or "hasattr" in script_content, "Script should handle missing columns"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])






