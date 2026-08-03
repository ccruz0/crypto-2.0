import { describe, expect, it, beforeEach, afterEach } from 'vitest';
import { getClientApiKey } from './clientApiKey';

describe('getClientApiKey', () => {
  const original = process.env.NEXT_PUBLIC_ATP_API_KEY;

  afterEach(() => {
    if (original === undefined) {
      delete process.env.NEXT_PUBLIC_ATP_API_KEY;
    } else {
      process.env.NEXT_PUBLIC_ATP_API_KEY = original;
    }
  });

  beforeEach(() => {
    delete process.env.NEXT_PUBLIC_ATP_API_KEY;
  });

  it('falls back to demo-key when unset', () => {
    expect(getClientApiKey()).toBe('demo-key');
  });

  it('returns trimmed NEXT_PUBLIC_ATP_API_KEY when set', () => {
    process.env.NEXT_PUBLIC_ATP_API_KEY = '  prod-key-value  ';
    expect(getClientApiKey()).toBe('prod-key-value');
  });
});
