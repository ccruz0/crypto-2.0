import { describe, expect, it } from 'vitest';
import {
  isInternalApiProxyPath,
} from '@/lib/internalApiProxy';

// getBackendApiKey tested indirectly via bracket-access pattern in server module
describe('internalApiProxy', () => {
  it('allows create-protection-smart path', () => {
    expect(isInternalApiProxyPath('orders/create-protection-smart')).toBe(true);
    expect(isInternalApiProxyPath('/orders/create-protection-smart')).toBe(true);
  });

  it('rejects unknown paths', () => {
    expect(isInternalApiProxyPath('orders/cancel')).toBe(false);
    expect(isInternalApiProxyPath('admin/test-telegram')).toBe(false);
  });
});
