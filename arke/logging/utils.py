"""Utility functions for logging (secrets masking, sanitization)."""

import re


def mask_api_keys(text: str) -> str:
    """Mask common API key patterns."""
    patterns = [
        (r'(api[_-]?key)[=:\s]+["\']?([^"\'\s]+)["\']?', r'\1=***'),
        (r'(secret)[=:\s]+["\']?([^"\'\s]+)["\']?', r'\1=***'),
        (r'(token)[=:\s]+["\']?([^"\'\s]+)["\']?', r'\1=***'),
    ]
    
    result = text
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def sanitize_for_logs(data: str, max_length: int = 500) -> str:
    """Sanitize user data for logging (truncate + strip sensitive)."""
    if len(data) > max_length:
        data = data[:max_length - 3] + "..."
    return data
