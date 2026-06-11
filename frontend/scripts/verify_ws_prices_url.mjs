#!/usr/bin/env node
/**
 * Verifies getWebSocketPricesUrl() behavior without a browser.
 * Run: node frontend/scripts/verify_ws_prices_url.mjs
 */

const PRICE_STREAM_WS_PATH = '/api/ws/prices';
const ABSOLUTE_OVERRIDE_PREFIX = /^(?:ws|wss|https?):\/\//i;
const INTERNAL_HOSTNAMES = new Set([
  'api',
  'backend',
  'backend-aws',
  'backend-aws-canary',
]);

function isLocalHostname(hostname) {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]';
}

function isProductionBrowserContext(location) {
  return !isLocalHostname(location.hostname);
}

function isRejectedOverrideHostname(hostname, location) {
  if (INTERNAL_HOSTNAMES.has(hostname)) return true;
  if (isProductionBrowserContext(location) && isLocalHostname(hostname)) return true;
  return false;
}

function isValidAbsoluteOverride(override, location) {
  if (!override || !ABSOLUTE_OVERRIDE_PREFIX.test(override)) return false;
  try {
    const u = new URL(override);
    return !isRejectedOverrideHostname(u.hostname, location);
  } catch {
    return false;
  }
}

function normalizePriceStreamWsUrl(override, location) {
  const u = new URL(override);
  const pageSecure = location.protocol === 'https:';
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

function getWebSocketPricesUrl(location, envOverride) {
  const override = envOverride?.trim();
  if (override && isValidAbsoluteOverride(override, location)) {
    return normalizePriceStreamWsUrl(override, location);
  }
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${location.host}${PRICE_STREAM_WS_PATH}`;
}

const cases = [
  {
    name: 'HTTPS production dashboard',
    location: { protocol: 'https:', host: 'dashboard.hilovivo.com', hostname: 'dashboard.hilovivo.com' },
    env: undefined,
    want: 'wss://dashboard.hilovivo.com/api/ws/prices',
  },
  {
    name: 'HTTP localhost',
    location: { protocol: 'http:', host: 'localhost:3000', hostname: 'localhost' },
    env: undefined,
    want: 'ws://localhost:3000/api/ws/prices',
  },
  {
    name: 'relative env override falls back',
    location: { protocol: 'https:', host: 'dashboard.hilovivo.com', hostname: 'dashboard.hilovivo.com' },
    env: '/api',
    want: 'wss://dashboard.hilovivo.com/api/ws/prices',
  },
  {
    name: 'internal ws://api override falls back',
    location: { protocol: 'https:', host: 'dashboard.hilovivo.com', hostname: 'dashboard.hilovivo.com' },
    env: 'ws://api/ws/prices',
    want: 'wss://dashboard.hilovivo.com/api/ws/prices',
  },
  {
    name: 'HTTPS page normalizes https override',
    location: { protocol: 'https:', host: 'dashboard.hilovivo.com', hostname: 'dashboard.hilovivo.com' },
    env: 'https://example.com/api/ws/prices',
    want: 'wss://example.com/api/ws/prices',
  },
];

let failed = 0;
for (const c of cases) {
  const got = getWebSocketPricesUrl(c.location, c.env);
  if (got !== c.want) {
    console.error(`FAIL ${c.name}\n  want: ${c.want}\n  got:  ${got}`);
    failed += 1;
  } else {
    console.log(`OK   ${c.name}`);
  }
}

if (failed > 0) {
  process.exit(1);
}
console.log('All WebSocket URL checks passed.');
