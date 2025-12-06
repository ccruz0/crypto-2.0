"""
Crypto.com Exchange v1 WebSocket Client
Subscribes to user channel for real-time updates (balances, orders, trades)
"""

import os
import json
import hmac
import hashlib
import time
import asyncio
import logging
from typing import Dict, Callable, Optional
import websockets
from websockets.client import WebSocketClientProtocol

from .crypto_com_constants import WS_USER

logger = logging.getLogger(__name__)


class CryptoComWebSocketClient:
    """WebSocket client for Crypto.com Exchange v1 User Channel"""
    
    def __init__(self):
        self.ws_url = WS_USER
        self.api_key = os.getenv("EXCHANGE_CUSTOM_API_KEY", "").strip()
        self.api_secret = os.getenv("EXCHANGE_CUSTOM_API_SECRET", "").strip()
        self.ws: Optional[WebSocketClientProtocol] = None
        self.connected = False
        self.subscribed = False
        self.reconnect_interval = 5  # seconds
        self.max_reconnect_attempts = 10
        
        # Callbacks for different event types
        self.callbacks: Dict[str, Callable] = {}
        
        # Current state
        self.balance_data = {}
        self.orders_data = []
    
    def generate_signature(self, method: str, params: dict = None) -> str:
        """Generate HMAC-SHA256 signature for WebSocket authentication"""
        params_str = json.dumps(params or {}, separators=(',', ':'))
        nonce = int(time.time() * 1000)
        payload = f"{method}{nonce}{self.api_key}{params_str}"
        
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature, nonce
    
    async def authenticate(self):
        """Authenticate WebSocket connection"""
        if not self.api_key or not self.api_secret:
            logger.error("API credentials not set for WebSocket authentication")
            return False
        
        try:
            signature, nonce = self.generate_signature("public/auth")
            
            auth_message = {
                "id": int(time.time() * 1000),
                "method": "public/auth",
                "params": {
                    "api_key": self.api_key,
                    "sig": signature,
                    "nonce": nonce
                }
            }
            
            logger.info("Authenticating WebSocket connection...")
            await self.ws.send(json.dumps(auth_message))
            
            # Wait for authentication response
            response = await asyncio.wait_for(self.ws.recv(), timeout=5)
            data = json.loads(response)
            
            if data.get("method") == "public/auth" and data.get("code") == 0:
                logger.info("WebSocket authenticated successfully")
                return True
            else:
                logger.error(f"WebSocket authentication failed: {data}")
                return False
                
        except asyncio.TimeoutError:
            logger.error("WebSocket authentication timeout")
            return False
        except Exception as e:
            logger.error(f"WebSocket authentication error: {e}")
            return False
    
    async def subscribe_user_channel(self):
        """Subscribe to user channel for account updates"""
        try:
            subscription = {
                "method": "subscribe",
                "params": {
                    "channels": ["user.balance", "user.order", "user.trade"]
                }
            }
            
            logger.info("Subscribing to user channel...")
            await self.ws.send(json.dumps(subscription))
            
            # Wait for subscription confirmation
            response = await asyncio.wait_for(self.ws.recv(), timeout=5)
            data = json.loads(response)
            
            if data.get("method") == "subscribe" and data.get("code") == 0:
                logger.info("Successfully subscribed to user channel")
                self.subscribed = True
                return True
            else:
                logger.error(f"Subscription failed: {data}")
                return False
                
        except asyncio.TimeoutError:
            logger.error("Subscription timeout")
            return False
        except Exception as e:
            logger.error(f"Subscription error: {e}")
            return False
    
    def register_callback(self, event_type: str, callback: Callable):
        """Register a callback for specific event type"""
        self.callbacks[event_type] = callback
        logger.info(f"Registered callback for event type: {event_type}")
    
    def handle_message(self, data: dict):
        """Handle incoming WebSocket messages"""
        method = data.get("method", "")
        
        if method == "user.balance":
            self.balance_data = data.get("data", {})
            if "balance" in self.callbacks:
                self.callbacks["balance"](self.balance_data)
            logger.debug("Balance updated")
            
        elif method == "user.order":
            order_data = data.get("data", {})
            if "order" in self.callbacks:
                self.callbacks["order"](order_data)
            logger.debug(f"Order update: {order_data}")
            
        elif method == "user.trade":
            trade_data = data.get("data", {})
            if "trade" in self.callbacks:
                self.callbacks["trade"](trade_data)
            logger.debug(f"Trade update: {trade_data}")
            
        elif method == "public/auth":
            # Authentication response already handled
            pass
        else:
            logger.debug(f"Unhandled message type: {method}")
    
    async def listen(self):
        """Listen for incoming messages"""
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)
                    self.handle_message(data)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON received: {message}")
                except Exception as e:
                    logger.error(f"Error handling message: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            self.connected = False
            self.subscribed = False
        except Exception as e:
            logger.error(f"Error in WebSocket listener: {e}")
            self.connected = False
            self.subscribed = False
    
    async def connect(self):
        """Establish WebSocket connection and authenticate"""
        try:
            logger.info(f"Connecting to {self.ws_url}...")
            self.ws = await websockets.connect(self.ws_url)
            self.connected = True
            logger.info("WebSocket connected")
            
            # Authenticate
            if await self.authenticate():
                # Subscribe to user channel
                await self.subscribe_user_channel()
                return True
            else:
                await self.ws.close()
                self.connected = False
                return False
                
        except Exception as e:
            logger.error(f"Error connecting to WebSocket: {e}")
            self.connected = False
            return False
    
    async def reconnect(self):
        """Reconnect with exponential backoff"""
        for attempt in range(self.max_reconnect_attempts):
            wait_time = min(self.reconnect_interval * (2 ** attempt), 60)
            logger.info(f"Reconnecting in {wait_time} seconds (attempt {attempt + 1}/{self.max_reconnect_attempts})...")
            await asyncio.sleep(wait_time)
            
            if await self.connect():
                logger.info("Reconnected successfully")
                return True
        
        logger.error("Max reconnection attempts reached")
        return False
    
    async def start(self):
        """Start WebSocket connection and listening loop"""
        while True:
            if await self.connect():
                await self.listen()
            
            # If we get here, connection was lost - try to reconnect
            if not self.connected:
                logger.info("Connection lost, attempting to reconnect...")
                if not await self.reconnect():
                    logger.error("Failed to reconnect, giving up")
                    break
    
    async def stop(self):
        """Stop WebSocket connection"""
        if self.ws:
            await self.ws.close()
        self.connected = False
        self.subscribed = False
        logger.info("WebSocket connection closed")


# Global WebSocket client instance
_ws_client: Optional[CryptoComWebSocketClient] = None

def get_ws_client() -> CryptoComWebSocketClient:
    """Get or create WebSocket client singleton"""
    global _ws_client
    if _ws_client is None:
        _ws_client = CryptoComWebSocketClient()
    return _ws_client
