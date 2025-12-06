"""
Shared storage for market cache data.
This module provides functions to read/write cache data to a JSON file,
allowing both the API server and the updater worker to share the same cache.
"""
import json
import os
import time
import logging
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

# Path to the cache file (shared between processes)
# Use /tmp for better permissions compatibility in Docker
CACHE_FILE_PATH = os.getenv("MARKET_CACHE_PATH", os.path.join("/tmp", "market_cache.json"))


def save_cache_to_storage(data: Dict) -> None:
    """Save cache data to shared storage (JSON file)"""
    try:
        cache_data = {
            "coins": data.get("coins", []),
            "count": data.get("count", 0),
            "timestamp": time.time(),
            "source": "cache"
        }
        
        # Ensure directory exists
        cache_dir = os.path.dirname(CACHE_FILE_PATH)
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
        
        # Write to file atomically
        temp_file = CACHE_FILE_PATH + ".tmp"
        try:
            with open(temp_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            
            # Atomic move
            os.replace(temp_file, CACHE_FILE_PATH)
            
            logger.debug(f"Cache saved to {CACHE_FILE_PATH}: {cache_data['count']} items")
        except PermissionError as pe:
            # If we can't write to the file, log but don't crash
            logger.warning(f"Permission denied writing cache to {CACHE_FILE_PATH}: {pe}. Cache will not be persisted, but service will continue.")
        except OSError as oe:
            # Handle other OS errors (e.g., disk full, read-only filesystem)
            logger.warning(f"OS error writing cache to {CACHE_FILE_PATH}: {oe}. Cache will not be persisted, but service will continue.")
    except Exception as e:
        # Don't raise - just log the error so the service continues
        logger.error(f"Error saving cache to storage: {e}", exc_info=True)


def load_cache_from_storage() -> Optional[Dict]:
    """Load cache data from shared storage (JSON file)"""
    try:
        if not os.path.exists(CACHE_FILE_PATH):
            logger.debug(f"Cache file not found: {CACHE_FILE_PATH}")
            return None
        
        with open(CACHE_FILE_PATH, 'r') as f:
            cache_data = json.load(f)
        
        # Validate structure
        if not isinstance(cache_data, dict):
            logger.warning("Invalid cache data structure")
            return None
        
        # Add cache age info
        if "timestamp" in cache_data:
            cache_age = time.time() - cache_data["timestamp"]
            cache_data["cache_age"] = cache_age
        
        logger.debug(f"Cache loaded from {CACHE_FILE_PATH}: {cache_data.get('count', 0)} items")
        return cache_data
        
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding cache JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Error loading cache from storage: {e}", exc_info=True)
        return None


def get_empty_cache_response() -> Dict:
    """Return empty cache response structure"""
    return {
        "ok": True,
        "source": "empty-cache",
        "coins": [],
        "count": 0
    }


def clear_cache() -> None:
    """Clear the cache file"""
    try:
        if os.path.exists(CACHE_FILE_PATH):
            os.remove(CACHE_FILE_PATH)
            logger.info("Cache file cleared")
    except Exception as e:
        logger.error(f"Error clearing cache: {e}", exc_info=True)

