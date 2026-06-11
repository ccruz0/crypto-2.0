/**
 * WebSocket URL for the backend price stream (/api/ws/prices).
 * Never derive from relative HTTP API bases like "/api" (that yields ws://api/ws/prices).
 * Browser: same-origin wss on HTTPS, ws on HTTP.
 */

export const PRICE_STREAM_WS_PATH = '/api/ws/prices';

function isLocalHostname(hostname: string): boolean {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]';
}

function isInternalApiHostname(hostname: string): boolean {
  return hostname === 'api' || hostname === 'backend-aws' || hostname.includes('backend-aws');
}

function buildSameOriginPriceStreamWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${PRICE_STREAM_WS_PATH}`;
}

/** Normalize NEXT_PUBLIC_WS_PRICES_URL for the current page (https => wss, http => ws). */
function normalizePriceStreamWsUrl(override: string): string {
  if (typeof window === 'undefined') {
    return override;
  }
  try {
    const u = new URL(override, window.location.href);
    const pageSecure = window.location.protocol === 'https:';

    if (isInternalApiHostname(u.hostname)) {
      return buildSameOriginPriceStreamWsUrl();
    }

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

function sanitizePriceStreamWsUrl(url: string): string {
  if (typeof window === 'undefined') {
    return url;
  }
  if (/^wss?:\/\/api(?:\/|$)/i.test(url)) {
    return buildSameOriginPriceStreamWsUrl();
  }
  try {
    const u = new URL(url, window.location.href);
    if (isInternalApiHostname(u.hostname)) {
      return buildSameOriginPriceStreamWsUrl();
    }
    if (window.location.protocol === 'https:' && u.protocol === 'ws:' && !isLocalHostname(u.hostname)) {
      u.protocol = 'wss:';
      return u.toString();
    }
  } catch {
    /* use url as-is */
  }
  return url;
}

/**
 * WebSocket URL for real-time price stream (/api/ws/prices).
 * Optional NEXT_PUBLIC_WS_PRICES_URL override (full ws(s)://, http(s)://, or path URL).
 */
export function getWebSocketPricesUrl(): string {
  const override = process.env.NEXT_PUBLIC_WS_PRICES_URL?.trim();
  if (override) {
    if (typeof window === 'undefined') {
      return override;
    }
    return sanitizePriceStreamWsUrl(normalizePriceStreamWsUrl(override));
  }

  if (typeof window === 'undefined') {
    return `ws://127.0.0.1:8002${PRICE_STREAM_WS_PATH}`;
  }

  return buildSameOriginPriceStreamWsUrl();
}
