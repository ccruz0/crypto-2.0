"""
Tests for environment configuration and URL normalization
"""
import pytest
import os
import sys
from pathlib import Path
from unittest.mock import patch

# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.environment import (
    get_api_base_url,
    get_frontend_url,
    get_cors_origins,
    _normalize_cors_origin,
)


class TestURLNormalization:
    """Test URL normalization in get_api_base_url and get_frontend_url"""
    
    def test_get_api_base_url_with_trailing_slash(self):
        """Test that trailing slashes are normalized"""
        with patch.dict(os.environ, {
            'ENVIRONMENT': 'aws',
            'API_BASE_URL': 'https://dashboard.hilovivo.com/api/',
            'PUBLIC_BASE_URL': '',
        }, clear=False):
            result = get_api_base_url()
            assert result == 'https://dashboard.hilovivo.com/api'
            assert not result.endswith('/')
    
    def test_get_api_base_url_from_public_base_url(self):
        """Test PUBLIC_BASE_URL normalization and /api appending"""
        with patch.dict(os.environ, {
            'ENVIRONMENT': 'aws',
            'API_BASE_URL': '',
            'PUBLIC_BASE_URL': 'https://dashboard.hilovivo.com/',
        }, clear=False):
            result = get_api_base_url()
            assert result == 'https://dashboard.hilovivo.com/api'
            assert not result.endswith('//')
    
    def test_get_api_base_url_public_base_url_already_has_api(self):
        """Test PUBLIC_BASE_URL that already includes /api"""
        with patch.dict(os.environ, {
            'ENVIRONMENT': 'aws',
            'API_BASE_URL': '',
            'PUBLIC_BASE_URL': 'https://dashboard.hilovivo.com/api',
        }, clear=False):
            result = get_api_base_url()
            assert result == 'https://dashboard.hilovivo.com/api'
            assert result.count('/api') == 1
    
    def test_get_frontend_url_with_trailing_slash(self):
        """Test that frontend URL trailing slashes are normalized"""
        with patch.dict(os.environ, {
            'ENVIRONMENT': 'aws',
            'FRONTEND_URL': 'https://dashboard.hilovivo.com/',
            'PUBLIC_BASE_URL': '',
        }, clear=False):
            result = get_frontend_url()
            assert result == 'https://dashboard.hilovivo.com'
            assert not result.endswith('/')
    
    def test_get_frontend_url_from_public_base_url(self):
        """Test PUBLIC_BASE_URL normalization for frontend"""
        with patch.dict(os.environ, {
            'ENVIRONMENT': 'aws',
            'FRONTEND_URL': '',
            'PUBLIC_BASE_URL': 'https://dashboard.hilovivo.com/',
        }, clear=False):
            result = get_frontend_url()
            assert result == 'https://dashboard.hilovivo.com'
            assert not result.endswith('/')


class TestCORSNormalization:
    """Test CORS origin normalization"""
    
    def test_normalize_cors_origin_removes_path(self):
        """Test that paths are removed from CORS origins"""
        assert _normalize_cors_origin('https://dashboard.hilovivo.com/api/health') == 'https://dashboard.hilovivo.com'
        assert _normalize_cors_origin('http://example.com:3000/path/to/page') == 'http://example.com:3000'
    
    def test_normalize_cors_origin_removes_query_and_fragment(self):
        """Test that query strings and fragments are removed"""
        assert _normalize_cors_origin('https://example.com?foo=bar') == 'https://example.com'
        assert _normalize_cors_origin('https://example.com#fragment') == 'https://example.com'
        assert _normalize_cors_origin('https://example.com/path?query#fragment') == 'https://example.com'
    
    def test_get_cors_origins_removes_duplicates(self):
        """Test that duplicate CORS origins are removed"""
        with patch.dict(os.environ, {
            'ENVIRONMENT': 'aws',
            'FRONTEND_URL': '',
            'PUBLIC_BASE_URL': '',
            'CORS_ORIGINS': 'https://example.com,https://example.com,https://test.com',
        }, clear=False):
            origins = get_cors_origins()
            # Should not have exact duplicates
            assert len(origins) == len(set(origins))
            # example.com should appear only once (plus http version if https provided)
            example_count = sum(1 for o in origins if 'example.com' in o)
            assert example_count <= 2  # https and http versions
            # test.com should appear
            assert any('test.com' in o for o in origins)
    
    def test_get_cors_origins_normalizes_paths(self):
        """Test that CORS origins from env vars have paths removed"""
        with patch.dict(os.environ, {
            'ENVIRONMENT': 'aws',
            'FRONTEND_URL': 'https://dashboard.hilovivo.com/api/health',
            'PUBLIC_BASE_URL': '',
        }, clear=False):
            origins = get_cors_origins()
            # All origins should be scheme://host:port format (no paths)
            for origin in origins:
                if origin != '*':
                    assert '/' not in origin.split('://')[1].split(':')[0] or origin.count('/') == 2  # Only scheme://host:port
                    assert '?' not in origin
                    assert '#' not in origin
