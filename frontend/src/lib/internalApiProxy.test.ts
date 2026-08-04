import { describe, expect, it } from 'vitest';
import {
  getBackendApiKey,
  isInternalApiProxyPath,
} from '@/lib/internalApiProxy';

describe('internalApiProxy', () => {
  it('allows create-protection-smart path', () => {
    expect(isInternalApiProxyPath('orders/create-protection-smart')).toBe(true);
    expect(isInternalApiProxyPath('/orders/create-protection-smart')).toBe(true);
  });

  it('rejects unknown paths', () => {
    expect(isInternalApiProxyPath('orders/cancel')).toBe(false);
    expect(isInternalApiProxyPath('admin/test-telegram')).toBe(false);
  });

  it('falls back to demo-key when env unset', () => {
    const prevAtp = process.env.ATP_API_KEY;
    const prevInternal = process.env.INTERNAL_API_KEY;
    delete process.env.ATP_API_KEY;
    delete process.env.INTERNAL_API_KEY;
    expect(getBackendApiKey()).toBe('demo-key');
    if (prevAtp !== undefined) process.env.ATP_API_KEY = prevAtp;
    if (prevInternal !== undefined) process.env.INTERNAL_API_KEY = prevInternal;
  });
});
