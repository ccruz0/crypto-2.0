/**
 * Dashboard x-api-key sent to the backend.
 * NEXT_PUBLIC_ATP_API_KEY is inlined at `next build` (CI build-arg / local env).
 * Falls back to demo-key for local when unset (matches backend auth fallback).
 */
export function getClientApiKey(): string {
  const key = (process.env.NEXT_PUBLIC_ATP_API_KEY || '').trim();
  return key || 'demo-key';
}
