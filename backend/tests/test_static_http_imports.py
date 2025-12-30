"""
Static check to ensure no direct HTTP library imports outside http_client.py

This test fails if requests, aiohttp, or urllib.request are imported
directly in application code (outside http_client.py and test files).
"""
import os
import re
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_no_direct_http_imports():
    """Test that no files import HTTP libraries directly"""
    backend_path = Path(__file__).parent.parent / "app"
    
    # Patterns to check for
    forbidden_patterns = [
        (r'^\s*import requests\s*$', 'import requests'),
        (r'^\s*from requests import', 'from requests import'),
        (r'^\s*import aiohttp\s*$', 'import aiohttp'),
        (r'^\s*from aiohttp import', 'from aiohttp import'),
        (r'^\s*import urllib\.request\s*$', 'import urllib.request'),
        (r'^\s*from urllib import request', 'from urllib import request'),
    ]
    
    violations = []
    
    # Walk through all Python files
    for py_file in backend_path.rglob("*.py"):
        # Skip test files and http_client.py itself
        if 'test' in py_file.name.lower() or 'http_client.py' in str(py_file):
            continue
        
        # Skip __pycache__
        if '__pycache__' in str(py_file):
            continue
        
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            for line_num, line in enumerate(lines, 1):
                for pattern, description in forbidden_patterns:
                    if re.match(pattern, line):
                        violations.append({
                            'file': str(py_file.relative_to(Path(__file__).parent.parent)),
                            'line': line_num,
                            'pattern': description,
                            'content': line.strip()
                        })
        except Exception as e:
            # Skip files that can't be read
            continue
    
    if violations:
        error_msg = "Direct HTTP library imports found outside http_client.py:\n\n"
        for v in violations:
            error_msg += f"  {v['file']}:{v['line']} - {v['pattern']}\n"
            error_msg += f"    {v['content']}\n\n"
        error_msg += "All outbound HTTP requests must use app.utils.http_client"
        assert False, error_msg


def test_no_direct_http_calls():
    """Test that no files make direct HTTP calls"""
    backend_path = Path(__file__).parent.parent / "app"
    
    # Patterns to check for
    forbidden_patterns = [
        (r'requests\.(get|post)\(', 'requests.get/post()'),
        (r'aiohttp\.ClientSession\(', 'aiohttp.ClientSession()'),
        (r'urllib\.request\.(urlopen|Request)\(', 'urllib.request.urlopen/Request()'),
    ]
    
    violations = []
    
    # Walk through all Python files
    for py_file in backend_path.rglob("*.py"):
        # Skip test files and http_client.py itself
        if 'test' in py_file.name.lower() or 'http_client.py' in str(py_file):
            continue
        
        # Skip __pycache__
        if '__pycache__' in str(py_file):
            continue
        
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            for pattern, description in forbidden_patterns:
                if re.search(pattern, content):
                    # Find line numbers
                    lines = content.split('\n')
                    for line_num, line in enumerate(lines, 1):
                        if re.search(pattern, line):
                            violations.append({
                                'file': str(py_file.relative_to(Path(__file__).parent.parent)),
                                'line': line_num,
                                'pattern': description,
                                'content': line.strip()[:100]
                            })
        except Exception as e:
            # Skip files that can't be read
            continue
    
    if violations:
        error_msg = "Direct HTTP calls found outside http_client.py:\n\n"
        for v in violations[:20]:  # Limit to first 20
            error_msg += f"  {v['file']}:{v['line']} - {v['pattern']}\n"
            error_msg += f"    {v['content']}\n\n"
        if len(violations) > 20:
            error_msg += f"  ... and {len(violations) - 20} more violations\n\n"
        error_msg += "All outbound HTTP requests must use app.utils.http_client"
        assert False, error_msg


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])











