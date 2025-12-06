"""Utility functions for redacting sensitive information from logs"""
import re
from typing import Any, Dict, Union


def redact_secrets(data: Any, max_length: int = 100) -> Any:
    """
    Redact sensitive information from data to prevent logging secrets.
    
    Args:
        data: The data to redact (dict, list, str, etc.)
        max_length: Maximum length of string values before truncation
        
    Returns:
        Data with sensitive fields redacted
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            key_lower = str(key).lower()
            # Redact sensitive fields
            if any(sensitive in key_lower for sensitive in ['secret', 'password', 'token', 'key', 'api_key', 'api_secret']):
                result[key] = "***REDACTED***"
            else:
                result[key] = redact_secrets(value, max_length)
        return result
    elif isinstance(data, list):
        return [redact_secrets(item, max_length) for item in data]
    elif isinstance(data, str):
        # Truncate long strings
        if len(data) > max_length:
            return data[:max_length] + "..."
        return data
    else:
        return data
