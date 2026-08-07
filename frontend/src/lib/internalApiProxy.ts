/**
 * Server-side proxy allowlist for dashboard mutations that require ATP_API_KEY.
 * Browser calls /internal-api/* (Next.js route) which forwards to the backend
 * with the key from env — never exposed to the client bundle.
 */

export const INTERNAL_API_PROXY_PATHS = new Set([
  'orders/create-protection-smart',
  'orders/create-sl-tp-with-details',
]);

export function isInternalApiProxyPath(path: string): boolean {
  return INTERNAL_API_PROXY_PATHS.has(path.replace(/^\/+/, ''));
}

/** True when the browser should call /internal-api instead of /api for auth-gated POSTs. */
export function shouldUseInternalApiProxy(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }
  const host = window.location.hostname;
  return (
    host.includes('hilovivo.com') ||
    host.includes('hilovivo') ||
    process.env.NEXT_PUBLIC_USE_INTERNAL_API_PROXY === 'true'
  );
}
