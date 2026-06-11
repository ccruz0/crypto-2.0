'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { getWebSocketPricesUrl } from '@/lib/priceStreamWsUrl';

export interface PriceStreamSnapshot {
  prices: Record<string, number>;
  ts: number;
  source?: string;
}

export interface PriceStreamContextValue {
  /** Live prices by base symbol (e.g. BTC, ETH). Empty when disconnected. */
  prices: Record<string, number>;
  /** Whether the WebSocket is currently connected. */
  connected: boolean;
  /** Unix timestamp (seconds) of last price update. */
  lastTs: number;
  /** Get price for a symbol (instrument_name like BTC_USDT or base like BTC). */
  getPrice: (symbol: string) => number | undefined;
}

const PriceStreamContext = createContext<PriceStreamContextValue | null>(null);

const RECONNECT_INITIAL_MS = 2000;
const RECONNECT_MAX_MS = 30000;

function baseSymbol(symbol: string): string {
  if (!symbol) return '';
  const base = symbol.split('_')[0];
  return base ? base.toUpperCase() : symbol.toUpperCase();
}

export function PriceStreamProvider({ children }: { children: ReactNode }) {
  const [prices, setPrices] = useState<Record<string, number>>({});
  const [connected, setConnected] = useState(false);
  const [lastTs, setLastTs] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelayRef = useRef(RECONNECT_INITIAL_MS);
  const mountedRef = useRef(true);

  const getPrice = useCallback((symbol: string): number | undefined => {
    const key = baseSymbol(symbol);
    return key ? prices[key] : undefined;
  }, [prices]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    function connect() {
      const url = getWebSocketPricesUrl();
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setConnected(true);
        reconnectDelayRef.current = RECONNECT_INITIAL_MS;
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
        try {
          const data = JSON.parse(event.data as string) as Record<string, unknown>;
          if (data.prices && typeof data.prices === 'object' && data.ts != null) {
            setPrices(data.prices as Record<string, number>);
            setLastTs(typeof data.ts === 'number' ? data.ts : Number(data.ts));
          }
        } catch {
          // ignore non-snapshot messages (e.g. { type: "keepalive" }, { type: "pong" })
        }
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setConnected(false);
        wsRef.current = null;
        const delay = reconnectDelayRef.current;
        reconnectDelayRef.current = Math.min(
          reconnectDelayRef.current * 2,
          RECONNECT_MAX_MS
        );
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectTimeoutRef.current = null;
          if (mountedRef.current) connect();
        }, delay);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, []);

  const value: PriceStreamContextValue = {
    prices,
    connected,
    lastTs,
    getPrice,
  };

  return (
    <PriceStreamContext.Provider value={value}>
      {children}
    </PriceStreamContext.Provider>
  );
}

export function usePriceStream(): PriceStreamContextValue {
  const ctx = useContext(PriceStreamContext);
  if (!ctx) {
    return {
      prices: {},
      connected: false,
      lastTs: 0,
      getPrice: () => undefined,
    };
  }
  return ctx;
}
