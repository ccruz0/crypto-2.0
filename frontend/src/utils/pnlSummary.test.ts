import { describe, expect, it } from 'vitest';
import type { OpenOrder, PortfolioAsset, TopCoin } from '@/app/api';
import { computePnLSummary, getPnLPeriodRange } from './pnlSummary';

function makeOrder(partial: Partial<OpenOrder> & Pick<OpenOrder, 'order_id' | 'side'>): OpenOrder {
  return {
    instrument_name: 'ETH_USD',
    order_type: 'LIMIT',
    quantity: '1',
    price: '100',
    status: 'FILLED',
    create_time: 1_000,
    update_time: 1_000,
    ...partial,
  };
}

function makeEntry(
  partial: Partial<OpenOrder> & Pick<OpenOrder, 'order_id' | 'side'>
): OpenOrder {
  return makeOrder({
    execution_origin: 'ALERT',
    order_type: 'MARKET',
    has_linked_tp: true,
    ...partial,
  });
}

function makeTpClose(
  partial: Partial<OpenOrder> & Pick<OpenOrder, 'order_id' | 'side' | 'parent_order_id'>
): OpenOrder {
  return makeOrder({
    order_type: 'TAKE_PROFIT_LIMIT',
    order_role: 'TAKE_PROFIT',
    execution_origin: 'TAKE_PROFIT',
    ...partial,
  });
}

describe('getPnLPeriodRange', () => {
  const now = new Date(2026, 6, 28, 15, 30, 0); // Jul 28, 2026 local

  it('today starts at local midnight', () => {
    const r = getPnLPeriodRange('today', now);
    expect(r.startMs).toBe(new Date(2026, 6, 28, 0, 0, 0, 0).getTime());
    expect(r.endMs).toBe(now.getTime());
  });

  it('7d / 30d are rolling windows', () => {
    const d7 = getPnLPeriodRange('7d', now);
    const d30 = getPnLPeriodRange('30d', now);
    expect(d7.startMs).toBe(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    expect(d30.startMs).toBe(now.getTime() - 30 * 24 * 60 * 60 * 1000);
  });

  it('month / year use calendar boundaries', () => {
    const month = getPnLPeriodRange('month', now);
    const year = getPnLPeriodRange('year', now);
    expect(month.startMs).toBe(new Date(2026, 6, 1, 0, 0, 0, 0).getTime());
    expect(year.startMs).toBe(new Date(2026, 0, 1, 0, 0, 0, 0).getTime());
  });

  it('custom uses inclusive local days', () => {
    const r = getPnLPeriodRange('custom', now, { from: '2026-07-01', to: '2026-07-10' });
    expect(r.startMs).toBe(new Date(2026, 6, 1, 0, 0, 0, 0).getTime());
    expect(r.endMs).toBe(new Date(2026, 6, 10, 23, 59, 59, 999).getTime());
  });
});

describe('computePnLSummary', () => {
  const now = new Date(2026, 6, 28, 12, 0, 0);

  it('sums realized closes in period only once (not entry+close)', () => {
    const buy = makeEntry({
      order_id: 'buy-1',
      side: 'BUY',
      quantity: '1',
      price: '100',
      create_time: new Date(2026, 6, 20).getTime(),
      update_time: new Date(2026, 6, 20).getTime(),
    });
    const sell = makeTpClose({
      order_id: 'sell-1',
      side: 'SELL',
      quantity: '1',
      price: '120',
      parent_order_id: 'buy-1',
      create_time: new Date(2026, 6, 25).getTime(),
      update_time: new Date(2026, 6, 25).getTime(),
    });

    const summary = computePnLSummary({
      executedOrders: [buy, sell],
      preset: '30d',
      now,
    });

    expect(summary.realizedPL).toBeCloseTo(20);
    expect(summary.closeCount).toBe(1);
    expect(summary.winCount).toBe(1);
    expect(summary.winRate).toBeCloseTo(1);
    expect(summary.tpExecutedCount).toBe(1);
    expect(summary.slExecutedCount).toBe(0);
  });

  it('counts FILLED TP and SL fills in the selected period', () => {
    const buy = makeEntry({
      order_id: 'buy-tp-sl',
      side: 'BUY',
      quantity: '2',
      price: '100',
      create_time: new Date(2026, 6, 10).getTime(),
      update_time: new Date(2026, 6, 10).getTime(),
    });
    const tp = makeTpClose({
      order_id: 'tp-1',
      side: 'SELL',
      quantity: '1',
      price: '120',
      parent_order_id: 'buy-tp-sl',
      create_time: new Date(2026, 6, 20).getTime(),
      update_time: new Date(2026, 6, 20).getTime(),
    });
    const sl = makeOrder({
      order_id: 'sl-1',
      side: 'SELL',
      quantity: '1',
      price: '90',
      order_type: 'STOP_LIMIT',
      order_role: 'STOP_LOSS',
      execution_origin: 'STOP_LOSS',
      parent_order_id: 'buy-tp-sl',
      create_time: new Date(2026, 6, 22).getTime(),
      update_time: new Date(2026, 6, 22).getTime(),
    });
    const oldTp = makeTpClose({
      order_id: 'tp-old',
      side: 'SELL',
      quantity: '1',
      price: '130',
      parent_order_id: 'buy-tp-sl',
      create_time: new Date(2026, 0, 5).getTime(),
      update_time: new Date(2026, 0, 5).getTime(),
    });
    const manualClose = makeOrder({
      order_id: 'manual-1',
      side: 'SELL',
      quantity: '1',
      price: '110',
      order_type: 'MARKET',
      execution_origin: 'MANUAL',
      create_time: new Date(2026, 6, 23).getTime(),
      update_time: new Date(2026, 6, 23).getTime(),
    });

    const summary = computePnLSummary({
      executedOrders: [buy, tp, sl, oldTp, manualClose],
      preset: '30d',
      now,
    });

    expect(summary.tpExecutedCount).toBe(1);
    expect(summary.slExecutedCount).toBe(1);
  });

  it('excludes closes outside the selected period', () => {
    const buy = makeEntry({
      order_id: 'buy-old',
      side: 'BUY',
      quantity: '1',
      price: '100',
      create_time: new Date(2026, 0, 1).getTime(),
      update_time: new Date(2026, 0, 1).getTime(),
    });
    const sell = makeTpClose({
      order_id: 'sell-old',
      side: 'SELL',
      quantity: '1',
      price: '150',
      parent_order_id: 'buy-old',
      create_time: new Date(2026, 0, 15).getTime(),
      update_time: new Date(2026, 0, 15).getTime(),
    });

    const summary = computePnLSummary({
      executedOrders: [buy, sell],
      preset: 'today',
      now,
    });

    expect(summary.realizedPL).toBe(0);
    expect(summary.closeCount).toBe(0);
    expect(summary.tpExecutedCount).toBe(0);
    expect(summary.slExecutedCount).toBe(0);
  });

  it('adds unrealized from open lots regardless of period', () => {
    const buy = makeEntry({
      order_id: 'open-buy',
      side: 'BUY',
      quantity: '2',
      price: '100',
      create_time: new Date(2025, 0, 1).getTime(),
      update_time: new Date(2025, 0, 1).getTime(),
    });
    const assets = [
      {
        coin: 'ETH',
        balance: 2,
        available_qty: 2,
        reserved_qty: 0,
        haircut: 0,
        value_usd: 220,
        updated_at: '',
      },
    ] as PortfolioAsset[];
    const topCoins = [
      {
        instrument_name: 'ETH_USD',
        current_price: 110,
      },
    ] as TopCoin[];

    const summary = computePnLSummary({
      executedOrders: [buy],
      portfolioAssets: assets,
      topCoins,
      preset: 'today',
      now,
    });

    expect(summary.realizedPL).toBe(0);
    expect(summary.unrealizedPL).toBeCloseTo(20); // (110-100)*2
    expect(summary.totalPL).toBeCloseTo(20);
  });

  it('aggregates top symbols by realized close P&L', () => {
    const ethBuy = makeEntry({
      order_id: 'eth-b',
      side: 'BUY',
      instrument_name: 'ETH_USD',
      quantity: '1',
      price: '100',
      create_time: new Date(2026, 6, 10).getTime(),
      update_time: new Date(2026, 6, 10).getTime(),
    });
    const ethSell = makeTpClose({
      order_id: 'eth-s',
      side: 'SELL',
      instrument_name: 'ETH_USD',
      quantity: '1',
      price: '130',
      parent_order_id: 'eth-b',
      create_time: new Date(2026, 6, 20).getTime(),
      update_time: new Date(2026, 6, 20).getTime(),
    });
    const btcBuy = makeEntry({
      order_id: 'btc-b',
      side: 'BUY',
      instrument_name: 'BTC_USD',
      quantity: '1',
      price: '100',
      create_time: new Date(2026, 6, 11).getTime(),
      update_time: new Date(2026, 6, 11).getTime(),
    });
    const btcSell = makeTpClose({
      order_id: 'btc-s',
      side: 'SELL',
      instrument_name: 'BTC_USD',
      quantity: '1',
      price: '105',
      parent_order_id: 'btc-b',
      create_time: new Date(2026, 6, 21).getTime(),
      update_time: new Date(2026, 6, 21).getTime(),
    });

    const summary = computePnLSummary({
      executedOrders: [ethBuy, ethSell, btcBuy, btcSell],
      preset: '30d',
      now,
      topN: 2,
    });

    expect(summary.topSymbols[0].symbol).toBe('ETH_USD');
    expect(summary.topSymbols[0].pnl).toBeCloseTo(30);
    expect(summary.topSymbols[1].symbol).toBe('BTC_USD');
    expect(summary.topSymbols[1].pnl).toBeCloseTo(5);
  });
});
