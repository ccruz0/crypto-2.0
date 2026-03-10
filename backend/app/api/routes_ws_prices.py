"""
WebSocket endpoint for real-time price stream.

Clients connect to /api/ws/prices and receive:
- On connect: one snapshot message { "prices": { "BTC": 45000.0, ... }, "ts": ..., "source": "crypto_com" }
- Then: the same shape pushed at PRICE_STREAM_INTERVAL_S (default 10s)

No auth required for the WebSocket; use only behind a trusted reverse proxy (e.g. dashboard).
"""

import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.price_stream import subscribe, unsubscribe

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/prices")
async def websocket_prices(websocket: WebSocket):
    """Stream live price updates to the dashboard. Same-origin or CORS should restrict access."""
    await websocket.accept()
    await subscribe(websocket)
    try:
        # Keep connection alive; client can optionally send ping or we just wait for disconnect
        while True:
            try:
                # Wait for any message (e.g. ping or close); timeout to allow periodic health check
                data = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                if data.strip().lower() == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # Send a keepalive so client knows we're still here
                await websocket.send_json({"type": "keepalive"})
            except WebSocketDisconnect:
                break
    except Exception as e:
        logger.debug("Price WebSocket closed: %s", e)
    finally:
        await unsubscribe(websocket)
