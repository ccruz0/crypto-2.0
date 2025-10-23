import copy
from typing import Any, Dict, List

def redact_secrets(obj: Any) -> Any:
    """
    Recursively redact sensitive fields from objects for logging
    """
    if isinstance(obj, dict):
        redacted = copy.deepcopy(obj)
        for key in ['api_key', 'api_secret', 'sig', 'secret', 'password', 'token']:
            if key in redacted:
                redacted[key] = "***REDACTED***"
        # Recurse into nested dicts
        for k, v in redacted.items():
            redacted[k] = redact_secrets(v)
        return redacted
    elif isinstance(obj, list):
        return [redact_secrets(item) for item in obj]
    else:
        return obj
