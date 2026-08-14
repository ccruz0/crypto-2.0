import { describe, expect, it } from 'vitest';
import {
  watchlistAmountText,
  watchlistAmountsFromItems,
  watchlistButtonOn,
  watchlistFlagsFromCoins,
} from './watchlistToggleState';

describe('watchlistButtonOn', () => {
  it('uses the DB/API row when overlay has no key', () => {
    expect(watchlistButtonOn({}, 'CRO_USD', true)).toBe(true);
    expect(watchlistButtonOn({}, 'CRO_USD', false)).toBe(false);
    expect(watchlistButtonOn(undefined, 'CRO_USD', true)).toBe(true);
  });

  it('does not treat missing overlay as NO when DB is YES', () => {
    expect(watchlistButtonOn({}, 'CRO_USD', true)).toBe(true);
  });

  it('uses overlay for in-flight optimistic clicks including explicit false', () => {
    expect(watchlistButtonOn({ CRO_USD: false }, 'CRO_USD', true)).toBe(false);
    expect(watchlistButtonOn({ CRO_USD: true }, 'CRO_USD', false)).toBe(true);
  });

  it('does not treat a missing master-alert overlay key as OFF when DB is ON', () => {
    expect(watchlistButtonOn({}, 'AAVE_USD', true)).toBe(true);
    expect(watchlistButtonOn({ AAVE_USD: true }, 'AAVE_USD', true)).toBe(true);
  });
});

describe('watchlistFlagsFromCoins', () => {
  it('normalizes instrument_name to uppercase keys from DB fields', () => {
    const flags = watchlistFlagsFromCoins([
      {
        instrument_name: 'cro_usd',
        trade_enabled: true,
        trade_on_margin: true,
        alert_enabled: true,
        buy_alert_enabled: false,
        sell_alert_enabled: true,
      },
    ]);
    expect(flags.trade.CRO_USD).toBe(true);
    expect(flags.margin.CRO_USD).toBe(true);
    expect(flags.alert.CRO_USD).toBe(true);
    expect(flags.buyAlert.CRO_USD).toBe(false);
    expect(flags.sellAlert.CRO_USD).toBe(true);
  });
});

describe('watchlistAmountText', () => {
  it('uses the DB amount when overlay has no key', () => {
    expect(watchlistAmountText({}, 'CRO_USD', 100)).toBe('100');
    expect(watchlistAmountText({}, 'DGB_USD', null)).toBe(null);
    expect(watchlistAmountText(undefined, 'DGB_USD', null)).toBe(null);
  });

  it('does not keep a stale overlay-less $10 when DB is null', () => {
    expect(watchlistAmountText({}, 'DGB_USD', null)).toBe(null);
    expect(watchlistAmountText({ AAVE_USD: '100' }, 'DGB_USD', null)).toBe(null);
  });

  it('uses overlay for in-flight edits including clearing', () => {
    expect(watchlistAmountText({ DGB_USD: '10' }, 'DGB_USD', null)).toBe('10');
    expect(watchlistAmountText({ DGB_USD: '' }, 'DGB_USD', 10)).toBe(null);
  });
});

describe('watchlistAmountsFromItems', () => {
  it('omits null DB amounts so DGB_USD does not inherit a leftover $10', () => {
    const amounts = watchlistAmountsFromItems([
      { symbol: 'CRO_USD', trade_amount_usd: 100 },
      { symbol: 'DGB_USD', trade_amount_usd: null },
      { instrument_name: 'GRAM_USDT', trade_amount_usd: 0.02 },
    ]);
    expect(amounts).toEqual({ CRO_USD: '100', GRAM_USDT: '0.02' });
    expect(Object.prototype.hasOwnProperty.call(amounts, 'DGB_USD')).toBe(false);
  });
});
