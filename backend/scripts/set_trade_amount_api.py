#!/usr/bin/env python3
"""
Script to set trade_amount_usd for a specific symbol using the API.
"""

import sys
import os
import requests
import json
import urllib3

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.environment import get_api_base_url, is_aws, is_local
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def set_trade_amount_via_api(symbol: str, amount_usd: float):
    """Set trade_amount_usd for a specific symbol using the API."""
    symbol = symbol.upper()
    
    # Get API base URL from environment (uses get_api_base_url() which handles local/AWS)
    try:
        api_base_url = get_api_base_url()
    except ValueError:
        # If AWS env vars are missing, fallback to localhost for local dev
        api_base_url = "http://localhost:8002"
    
    # Try the resolved URL first, then fallback to domain if needed
    api_base_urls_to_try = [api_base_url]
    # Add domain as fallback if not already included
    domain_api_url = "https://dashboard.hilovivo.com/api"
    if api_base_url != domain_api_url:
        api_base_urls_to_try.append(domain_api_url)
    
    response = None
    api_base_url = None
    
    # Step 1: Get the watchlist item by symbol to get its ID
    logger.info(f"Fetching watchlist item for {symbol}...")
    
    for url in api_base_urls_to_try:
        try:
            # Handle URLs that already include /api
            if url.endswith("/api"):
                get_url = f"{url}/dashboard/symbol/{symbol}"
            else:
                get_url = f"{url}/api/dashboard/symbol/{symbol}"
            logger.info(f"Trying API URL: {url}")
            response = requests.get(get_url, timeout=10, verify=False)  # Disable SSL verification for now
            
            # Check if we got a valid response (not 502, 503, etc.)
            if response.status_code >= 500:
                logger.warning(f"Server error {response.status_code} from {url}, trying next URL...")
                continue
            
            api_base_url = url
            logger.info(f"✅ Connected to {url}")
            break
        except requests.exceptions.ConnectionError as e:
            logger.debug(f"Connection failed to {url}: {e}")
            continue
        except Exception as e:
            logger.debug(f"Error with {url}: {e}")
            continue
    
    if not response or response.status_code >= 500:
        logger.error("❌ Could not connect to any API endpoint or server returned error")
        if response:
            logger.error(f"   Last response status: {response.status_code}")
            logger.error(f"   Last response body: {response.text[:200]}")
        return False
    
    try:
        if response.status_code == 404:
            logger.error(f"❌ Watchlist item not found for symbol: {symbol}")
            return False
        response.raise_for_status()
        item = response.json()
        item_id = item.get("id")
        
        if not item_id:
            logger.error(f"❌ Could not find ID in watchlist item response")
            return False
        
        logger.info(f"Found watchlist item ID: {item_id}")
        logger.info(f"Current trade_amount_usd: ${item.get('trade_amount_usd')}")
        
        # Step 2: Update the watchlist item using PUT /api/dashboard/{item_id}
        # Use the same base URL that worked for GET
        if api_base_url.endswith("/api"):
            update_url = f"{api_base_url}/dashboard/{item_id}"
        else:
            update_url = f"{api_base_url}/api/dashboard/{item_id}"
        payload = {
            "trade_amount_usd": amount_usd
        }
        
        logger.info(f"Updating trade_amount_usd to ${amount_usd}...")
        update_response = requests.put(
            update_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
            verify=False  # Disable SSL verification
        )
        update_response.raise_for_status()
        
        updated_item = update_response.json()
        logger.info(f"✅ Successfully updated {symbol}")
        logger.info(f"   New trade_amount_usd: ${updated_item.get('trade_amount_usd')}")
        logger.info(f"   trade_enabled: {updated_item.get('trade_enabled')}")
        logger.info(f"   trade_on_margin: {updated_item.get('trade_on_margin')}")
        
        return True
        
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ API request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"   Response status: {e.response.status_code}")
            logger.error(f"   Response body: {e.response.text}")
        return False
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Set trade_amount_usd for a specific symbol via API")
    parser.add_argument("symbol", type=str, help="Trading symbol (e.g., BTC_USD)")
    parser.add_argument("amount", type=float, help="Trade amount in USD")
    args = parser.parse_args()
    
    print("="*60)
    print("Set Trade Amount Script (via API)")
    print("="*60)
    print(f"Setting trade_amount_usd to ${args.amount} for {args.symbol}")
    print()
    success = set_trade_amount_via_api(args.symbol, args.amount)
    sys.exit(0 if success else 1)














