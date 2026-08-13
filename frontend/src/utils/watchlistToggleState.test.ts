import { describe, expect, it } from 'vitest';
import { watchlistButtonOn, watchlistFlagsFromCoins } from './watchlistToggleState';

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
