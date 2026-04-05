/**
 * WebSocket URL for the backend price stream (GET /api/ws/prices).
 * Never derive this from HTTP API base hostnames like "api" or "backend-aws" — use same-origin
 * (or NEXT_PUBLIC_WS_PRICES_URL) so HTTPS pages use wss:// and avoid mixed-content blocking.
 */

export const PRICE_STREAM_WS_PATH = '/api/ws/prices';

function isLocalHostname(hostname: string): boolean {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]';
}

/**
 * If NEXT_PUBLIC_WS_PRICES_URL is set, normalize scheme for the current page:
 * - https page + non-localhost host: prefer wss://
 * - http page: prefer ws://
 * - ws:// to localhost is kept even on https (dev edge cases)
 */
export function normalizePriceStreamWsUrl(override: string): string {
  if (typeof window === 'undefined') {
    return override;
  }
  try {
    const u = new URL(override, window.location.href);
    const pageSecure = window.location.protocol === 'https:';

    if (u.protocol === 'http:' || u.protocol === 'https:') {
      if (pageSecure && !isLocalHostname(u.hostname)) {
        u.protocol = 'wss:';
      } else if (!pageSecure) {
        u.protocol = 'ws:';
      } else if (pageSecure && isLocalHostname(u.hostname)) {
        u.protocol = 'ws:';
      } else {
        u.protocol = pageSecure ? 'wss:' : 'ws:';
      }
      return u.toString();
    }

    if (u.protocol === 'ws:' || u.protocol === 'wss:') {
      if (pageSecure && u.protocol === 'ws:' && !isLocalHostname(u.hostname)) {
        u.protocol = 'wss:';
      }
      return u.toString();
    }
  } catch {
    /* fall through */
  }
  return override;
}

/**
 * Client: same-origin WebSocket to PRICE_STREAM_WS_PATH (wss on https, ws on http).
 * Optional NEXT_PUBLIC_WS_PRICES_URL override (full ws(s):// or http(s):// URL).
 * SSR: returns a localhost default (callers should only open WebSocket in the browser).
 */
export function getPriceStreamWebSocketUrl(): string {
  const override = process.env.NEXT_PUBLIC_WS_PRICES_URL?.trim();
  if (override) {
    return typeof window === 'undefined' ? override : normalizePriceStreamWsUrl(override);
  }

  if (typeof window === 'undefined') {
    return `ws://127.0.0.1:8002${PRICE_STREAM_WS_PATH}`;
  }

  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${window.location.host}${PRICE_STREAM_WS_PATH}`;
}
