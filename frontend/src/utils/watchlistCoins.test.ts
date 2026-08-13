import { describe, expect, it } from 'vitest';
import { dedupeWatchlistCoins } from './watchlistCoins';

describe('dedupeWatchlistCoins', () => {
  it('keeps BTC/ETH USD and USDT pairs (separate DB rows)', () => {
    const coins = [
      { instrument_name: 'BTC_USD', trade_enabled: true },
      { instrument_name: 'ETH_USDT', trade_enabled: true },
      { instrument_name: 'ETH_USD', trade_enabled: true },
      { instrument_name: 'BTC_USDT', trade_enabled: false },
    ];
    expect(dedupeWatchlistCoins(coins).map(c => c.instrument_name)).toEqual([
      'BTC_USD',
      'ETH_USDT',
      'ETH_USD',
      'BTC_USDT',
    ]);
  });

  it('drops only exact instrument_name duplicates', () => {
    const coins = [
      { instrument_name: 'CRO_USD' },
      { instrument_name: 'cro_usd' },
      { instrument_name: 'CRO_USDT' },
    ];
    expect(dedupeWatchlistCoins(coins).map(c => c.instrument_name)).toEqual([
      'CRO_USD',
      'CRO_USDT',
    ]);
  });
});
