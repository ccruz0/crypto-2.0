'use client';

import { useEffect, useRef } from 'react';
import { getPriceStreamWebSocketUrl } from '@/lib/priceStreamWsUrl';

/**
 * Keeps a single price-stream WebSocket using same-origin wss:// on HTTPS (see getPriceStreamWebSocketUrl).
 * Disable with NEXT_PUBLIC_ENABLE_PRICE_WS=false if needed.
 */
export function usePriceWebSocket(options?: { enabled?: boolean }) {
  const enabled =
    options?.enabled ?? (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_ENABLE_PRICE_WS !== 'false');
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!enabled || typeof window === 'undefined') {
      return;
    }

    let ws: WebSocket;
    const url = getPriceStreamWebSocketUrl();
    try {
      ws = new WebSocket(url);
    } catch (e) {
      console.warn('[price-ws] WebSocket constructor failed:', e);
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      if (process.env.NODE_ENV === 'development') {
        console.debug('[price-ws] connected', url);
      }
    };
    ws.onerror = () => {
      /* Details appear in DevTools; do not throw */
    };
    ws.onclose = () => {
      wsRef.current = null;
    };

    return () => {
      try {
        ws.close();
      } catch {
        /* ignore */
      }
      wsRef.current = null;
    };
  }, [enabled]);
}
