"""
Test that diagnostics routes are properly registered.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app


def test_whoami_route_registered():
    """Test that /api/diagnostics/whoami route is registered."""
    client = TestClient(app)
    
    # Check OpenAPI schema
    openapi = client.get("/openapi.json").json()
    paths = openapi.get("paths", {})
    
    assert "/api/diagnostics/whoami" in paths, "whoami endpoint should be in OpenAPI schema"
    assert "get" in paths["/api/diagnostics/whoami"], "whoami should have GET method"


def test_reconcile_route_registered():
    """Test that /api/diagnostics/portfolio/reconcile route is registered."""
    client = TestClient(app)
    
    # Check OpenAPI schema
    openapi = client.get("/openapi.json").json()
    paths = openapi.get("paths", {})
    
    assert "/api/diagnostics/portfolio/reconcile" in paths, "reconcile endpoint should be in OpenAPI schema"
    assert "get" in paths["/api/diagnostics/portfolio/reconcile"], "reconcile should have GET method"


def test_whoami_gating_without_debug():
    """Test that whoami returns 403 when PORTFOLIO_DEBUG is not set and ENVIRONMENT is not local."""
    import os
    from unittest.mock import patch
    
    # Mock environment to be AWS without debug
    with patch.dict(os.environ, {"ENVIRONMENT": "aws", "PORTFOLIO_DEBUG": "0"}):
        client = TestClient(app)
        response = client.get("/api/diagnostics/whoami")
        
        assert response.status_code == 403, "Should return 403 when disabled"
        assert "detail" in response.json(), "Should have error detail"


def test_whoami_enabled_with_debug():
    """Test that whoami works when PORTFOLIO_DEBUG=1."""
    import os
    from unittest.mock import patch
    
    # Mock environment to have PORTFOLIO_DEBUG=1
    with patch.dict(os.environ, {"PORTFOLIO_DEBUG": "1"}):
        client = TestClient(app)
        response = client.get("/api/diagnostics/whoami")
        
        assert response.status_code == 200, "Should return 200 when enabled"
        assert "service_info" in response.json(), "Should have service_info"


def test_reconcile_gating_without_debug():
    """Test that reconcile returns 403 when PORTFOLIO_DEBUG is not set and ENVIRONMENT is not local."""
    import os
    from unittest.mock import patch
    
    # Mock environment to be AWS without debug
    with patch.dict(os.environ, {"ENVIRONMENT": "aws", "PORTFOLIO_DEBUG": "0"}):
        client = TestClient(app)
        response = client.get("/api/diagnostics/portfolio/reconcile")
        
        assert response.status_code == 403, "Should return 403 when disabled"
        assert "detail" in response.json(), "Should have error detail"
        assert "PORTFOLIO_DEBUG" in response.json()["detail"] or "ENVIRONMENT" in response.json()["detail"], "Error should mention PORTFOLIO_DEBUG or ENVIRONMENT"


def test_reconcile_enabled_with_debug():
    """Test that reconcile works when PORTFOLIO_DEBUG=1."""
    import os
    from unittest.mock import patch, MagicMock
    
    # Mock environment to have PORTFOLIO_DEBUG=1
    with patch.dict(os.environ, {"PORTFOLIO_DEBUG": "1"}):
        # Mock the portfolio_summary to avoid actual DB calls
        # Patch at source module since import happens inside the endpoint function.
        with patch("app.services.portfolio_cache.get_portfolio_summary") as mock_get_portfolio:
            
            # Setup mock portfolio summary
            mock_get_portfolio.return_value = {
                "total_value_usd": 1000.0,
                "portfolio_value_source": "exchange_wallet_balance",
                "reconcile": {
                    "raw_fields": {},
                    "candidates": {},
                    "chosen": {"value": 1000.0, "source": "exchange_wallet_balance"}
                }
            }
            
            # Mock the database dependency
            from app.database import get_db
            mock_db = MagicMock()
            
            # Override the dependency
            app.dependency_overrides[get_db] = lambda: mock_db
            
            try:
                client = TestClient(app)
                response = client.get("/api/diagnostics/portfolio/reconcile")
                
                assert response.status_code == 200, "Should return 200 when enabled"
                assert "exchange" in response.json(), "Should have exchange field"
                assert "total_value_usd" in response.json(), "Should have total_value_usd field"
                assert "raw_fields" in response.json(), "Should have raw_fields"
                assert "candidates" in response.json(), "Should have candidates"
                assert "chosen" in response.json(), "Should have chosen"
            finally:
                # Clean up dependency override
                app.dependency_overrides.clear()

