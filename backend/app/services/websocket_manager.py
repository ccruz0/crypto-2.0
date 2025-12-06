"""
WebSocket Manager Service
Manages the lifecycle of the Crypto.com WebSocket connection
"""

import asyncio
import logging
from app.services.brokers.crypto_com_websocket import get_ws_client

logger = logging.getLogger(__name__)

_ws_task = None

async def start_websocket_background():
    """Start WebSocket connection in background task"""
    global _ws_task
    
    if _ws_task is not None and not _ws_task.done():
        logger.info("WebSocket already running")
        return
    
    try:
        ws_client = get_ws_client()
        
        # Skip WebSocket if no API credentials
        if not ws_client.api_key or not ws_client.api_secret:
            logger.info("WebSocket skipped: No API credentials configured")
            return
        
        # Register callback for balance updates
        def on_balance_update(data):
            logger.info(f"Balance updated via WebSocket")
            # TODO: Update database/cache with new balance
        
        # Register callback for order updates
        def on_order_update(data):
            logger.info(f"Order updated via WebSocket")
            # TODO: Update database/cache with new order status
        
        # Register callback for trade updates
        def on_trade_update(data):
            logger.info(f"Trade executed via WebSocket")
            # TODO: Update database/cache with new trade
        
        ws_client.register_callback("balance", on_balance_update)
        ws_client.register_callback("order", on_order_update)
        ws_client.register_callback("trade", on_trade_update)
        
        # Start WebSocket in background task
        _ws_task = asyncio.create_task(ws_client.start())
        logger.info("WebSocket background task started")
        
    except Exception as e:
        logger.error(f"Failed to start WebSocket: {e}")
        logger.info("Will continue using REST API with TRADE_BOT fallback")

async def stop_websocket():
    """Stop WebSocket connection"""
    global _ws_task
    
    try:
        ws_client = get_ws_client()
        await ws_client.stop()
        
        if _ws_task and not _ws_task.done():
            _ws_task.cancel()
            try:
                await _ws_task
            except asyncio.CancelledError:
                pass
        
        _ws_task = None
        logger.info("WebSocket stopped")
        
    except Exception as e:
        logger.error(f"Error stopping WebSocket: {e}")

def is_websocket_connected() -> bool:
    """Check if WebSocket is connected"""
    try:
        ws_client = get_ws_client()
        return ws_client.connected
    except:
        return False
