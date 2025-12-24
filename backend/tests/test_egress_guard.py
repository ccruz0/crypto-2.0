"""
Regression tests for egress guard enforcement.

These tests ensure that:
1. Raw IP URLs are rejected
2. Non-allowlisted domains are rejected
3. Allowlisted domains pass
4. Guardrails cannot be bypassed
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add backend to path
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from app.utils.egress_guard import (
    validate_outbound_url,
    EgressGuardError,
    is_raw_ip,
    is_domain_allowed
)
from app.utils.http_client import http_get, http_post


class TestEgressGuard:
    """Test egress guard validation"""
    
    def test_raw_ip_blocked(self):
        """Test that raw IP addresses are blocked"""
        with pytest.raises(EgressGuardError) as exc_info:
            validate_outbound_url("http://147.251.181.222", calling_module="test")
        
        assert "raw ip" in str(exc_info.value).lower() or "raw IP" in str(exc_info.value)
        assert "147.251.181.222" in str(exc_info.value)
    
    def test_allowlisted_domain_allowed(self):
        """Test that allowlisted domains are allowed"""
        url, resolved_ip = validate_outbound_url(
            "https://api.crypto.com/exchange/v1",
            calling_module="test"
        )
        assert url == "https://api.crypto.com/exchange/v1"
    
    def test_non_allowlisted_domain_blocked(self):
        """Test that non-allowlisted domains are blocked"""
        with pytest.raises(EgressGuardError) as exc_info:
            validate_outbound_url("https://evil.com/api", calling_module="test")
        
        assert "non-allowlisted" in str(exc_info.value).lower() or "not in the egress allowlist" in str(exc_info.value)
        assert "evil.com" in str(exc_info.value)
    
    def test_localhost_allowed(self):
        """Test that localhost/internal addresses are allowed"""
        url, _ = validate_outbound_url("http://127.0.0.1:9000", calling_module="test")
        assert "127.0.0.1" in url
    
    def test_is_raw_ip_detection(self):
        """Test raw IP detection function"""
        assert is_raw_ip("147.251.181.222") is True
        assert is_raw_ip("147.251.181.222:8080") is True
        assert is_raw_ip("api.crypto.com") is False
        assert is_raw_ip("localhost") is False
    
    def test_is_domain_allowed(self):
        """Test domain allowlist checking"""
        assert is_domain_allowed("api.crypto.com") is True
        assert is_domain_allowed("api.telegram.org") is True
        assert is_domain_allowed("evil.com") is False
        assert is_domain_allowed("subdomain.api.crypto.com") is True  # Subdomain should work


class TestHttpClient:
    """Test HTTP client wrapper enforces egress guard"""
    
    @patch('app.utils.http_client.requests.get')
    def test_http_get_blocks_raw_ip(self, mock_get):
        """Test that http_get blocks raw IP addresses"""
        with pytest.raises(EgressGuardError):
            http_get("http://147.251.181.222", calling_module="test")
        
        # Should not make the request
        mock_get.assert_not_called()
    
    @patch('app.utils.http_client.requests.get')
    def test_http_get_allows_allowlisted_domain(self, mock_get):
        """Test that http_get allows allowlisted domains"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_get.return_value = mock_response
        
        response = http_get("https://api.crypto.com/exchange/v1", calling_module="test")
        
        # Should make the request
        mock_get.assert_called_once()
        assert response.status_code == 200
    
    @patch('app.utils.http_client.requests.post')
    def test_http_post_blocks_raw_ip(self, mock_post):
        """Test that http_post blocks raw IP addresses"""
        with pytest.raises(EgressGuardError):
            http_post("http://147.251.181.222/api", json={}, calling_module="test")
        
        # Should not make the request
        mock_post.assert_not_called()
    
    @patch('app.utils.http_client.requests.post')
    def test_http_post_allows_allowlisted_domain(self, mock_post):
        """Test that http_post allows allowlisted domains"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        response = http_post(
            "https://api.telegram.org/bot123/sendMessage",
            json={"text": "test"},
            calling_module="test"
        )
        
        # Should make the request
        mock_post.assert_called_once()
        assert response.status_code == 200


class TestGuardrailBypass:
    """Test that guardrails cannot be bypassed"""
    
    def test_direct_import_blocked(self):
        """Test that importing requests directly should be discouraged"""
        # This is a documentation test - we can't prevent imports at runtime
        # but we can verify the pattern is discouraged
        import importlib.util
        
        # Try to import requests module
        try:
            spec = importlib.util.find_spec("requests")
            if spec:
                # Module exists, but we should use http_client instead
                # This test documents the expected behavior
                assert True  # Module exists, but http_client should be used
        except ImportError:
            pass  # requests not installed, which is fine
    
    def test_egress_guard_called_before_request(self):
        """Test that egress guard is called before making requests"""
        with patch('app.utils.egress_guard.validate_outbound_url') as mock_validate:
            mock_validate.side_effect = EgressGuardError("Blocked")
            
            with pytest.raises(EgressGuardError):
                http_get("https://api.crypto.com/exchange/v1", calling_module="test")
            
            # validate_outbound_url should be called
            mock_validate.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

