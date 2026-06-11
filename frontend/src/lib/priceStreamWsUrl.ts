/**
 * WebSocket URL for the backend price stream (/api/ws/prices).
 * Never derive from relative HTTP API bases like "/api" (that yields ws://api/ws/prices).
 * Browser: same-origin wss on HTTPS, ws on HTTP.
 */

export const PRICE_STREAM_WS_PATH = '/api/ws/prices';

const ABSOLUTE_OVERRIDE_PREFIX = /^(?:ws|wss|https?):\/\//i;

const INTERNAL_HOSTNAMES = new Set([
  'api',
  'backend',
  'backend-aws',
  'backend-aws-canary',
]);

function isLocalHostname(hostname: string): boolean {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]';
}

function isProductionBrowserContext(): boolean {
  if (typeof window === 'undefined') return false;
  return !isLocalHostname(window.location.hostname);
}

function isRejectedOverrideHostname(hostname: string): boolean {
  if (INTERNAL_HOSTNAMES.has(hostname)) return true;
  if (isProductionBrowserContext() && isLocalHostname(hostname)) return true;
  return false;
}

function isValidAbsoluteOverride(override: string): boolean {
  if (!override || !ABSOLUTE_OVERRIDE_PREFIX.test(override)) {
    return false;
  }
  try {
    const u = new URL(override);
    return !isRejectedOverrideHostname(u.hostname);
  } catch {
    return false;
  }
}

function buildSameOriginPriceStreamWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${PRICE_STREAM_WS_PATH}`;
}

/** Normalize NEXT_PUBLIC_WS_PRICES_URL scheme to match the current page (https => wss, http => ws). */
function normalizePriceStreamWsUrl(override: string): string {
  const u = new URL(override);
  const pageSecure = window.location.protocol === 'https:';

  if (u.protocol === 'http:' || u.protocol === 'https:') {
    u.protocol = pageSecure ? 'wss:' : 'ws:';
    return u.toString();
  }

  if (u.protocol === 'ws:' || u.protocol === 'wss:') {
    u.protocol = pageSecure ? 'wss:' : 'ws:';
    return u.toString();
  }

  return override;
}

/**
 * WebSocket URL for real-time price stream (/api/ws/prices).
 * Optional NEXT_PUBLIC_WS_PRICES_URL override (full ws(s):// or http(s):// URL only).
 */
export function getWebSocketPricesUrl(): string {
  if (typeof window === 'undefined') {
    return PRICE_STREAM_WS_PATH;
  }

  const override = process.env.NEXT_PUBLIC_WS_PRICES_URL?.trim();
  if (override && isValidAbsoluteOverride(override)) {
    return normalizePriceStreamWsUrl(override);
  }

  return buildSameOriginPriceStreamWsUrl();
}
