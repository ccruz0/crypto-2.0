import { describe, expect, it } from 'vitest';
import { hasSisterBook, sisterInstrument, sisterQuote } from './sisterBooks';

describe('sisterBooks', () => {
  it('maps USD ↔ USDT', () => {
    expect(sisterQuote('USD')).toBe('USDT');
    expect(sisterQuote('USDT')).toBe('USD');
    expect(sisterQuote('BTC')).toBeNull();
  });

  it('builds sister instrument names', () => {
    expect(sisterInstrument('ETH_USD')).toBe('ETH_USDT');
    expect(sisterInstrument('BTC_USDT')).toBe('BTC_USD');
    expect(sisterInstrument('DOGE')).toBeNull();
  });

  it('detects sister book presence in a list', () => {
    const list = ['ETH_USD', 'ETH_USDT', 'BTC_USD'];
    expect(hasSisterBook('ETH_USD', list)).toBe(true);
    expect(hasSisterBook('BTC_USD', list)).toBe(false);
    expect(hasSisterBook('BTC_USDT', list)).toBe(true);
  });
});
