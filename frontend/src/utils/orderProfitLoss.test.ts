import { describe, expect, it } from 'vitest';
import { OpenOrder } from '@/app/api';
import {
  calculateOpenLotProfitLoss,
  calculateOrderProfitLoss,
  getOpenPositionLotsForAsset,
  rebuildOpenLots,
  trimOpenLotsToBalance,
} from './orderProfitLoss';

function makeOrder(partial: Partial<OpenOrder> & Pick<OpenOrder, 'order_id' | 'side'>): OpenOrder {
  return {
    instrument_name: 'ETH_USD',
    order_type: 'LIMIT',
    quantity: '0.05',
    price: '1800',
    status: 'FILLED',
    create_time: 1_000,
    update_time: 1_000,
    ...partial,
  };
}

describe('calculateOrderProfitLoss', () => {
  it('computes unrealized long P/L for BUY vs current price', () => {
    const buy = makeOrder({
      order_id: 'buy-1',
      side: 'BUY',
      quantity: '1',
      price: '100',
    });

    const result = calculateOrderProfitLoss(buy, [buy], 110, { positionHint: 'LONG' });

    expect(result.available).toBe(true);
    expect(result.isRealized).toBe(false);
    expect(result.pnl).toBeCloseTo(10);
    expect(result.pnlPercent).toBeCloseTo(10);
  });

  it('computes realized long exit when SELL matches prior BUY', () => {
    const buy = makeOrder({
      order_id: 'buy-1',
      side: 'BUY',
      quantity: '1',
      price: '100',
      create_time: 1_000,
      update_time: 1_000,
    });
    const sell = makeOrder({
      order_id: 'sell-1',
      side: 'SELL',
      quantity: '1',
      price: '120',
      create_time: 10_000,
      update_time: 10_000,
    });

    const result = calculateOrderProfitLoss(sell, [buy, sell], null, { positionHint: 'LONG' });

    expect(result.available).toBe(true);
    expect(result.isRealized).toBe(true);
    expect(result.pnl).toBeCloseTo(20);
    expect(result.pnlPercent).toBeCloseTo(20);
  });

  it('leaves unmatched long SELL unavailable', () => {
    const sell = makeOrder({
      order_id: 'sell-1',
      side: 'SELL',
      quantity: '1',
      price: '120',
    });

    const result = calculateOrderProfitLoss(sell, [sell], 100, { positionHint: 'LONG' });

    expect(result.available).toBe(false);
  });

  it('computes unrealized short P/L for SELL vs current price', () => {
    const sell = makeOrder({
      order_id: 'sell-1',
      side: 'SELL',
      quantity: '0.0532',
      price: '1876.73',
    });

    const currentPrice = 1842.8;
    const result = calculateOrderProfitLoss(sell, [sell], currentPrice, {
      positionHint: 'SHORT',
    });

    expect(result.available).toBe(true);
    expect(result.isRealized).toBe(false);
    expect(result.pnl).toBeCloseTo((1876.73 - currentPrice) * 0.0532, 4);
  });
});

describe('rebuildOpenLots / open-position filter', () => {
  it('drops fully liquidated round-trips from open lots', () => {
    const sellClosed = makeOrder({
      order_id: 'sell-old',
      side: 'SELL',
      quantity: '75.13',
      price: '137',
      instrument_name: 'SOL_USD',
      create_time: 1_000,
      update_time: 1_000,
    });
    const buyCover = makeOrder({
      order_id: 'buy-cover',
      side: 'BUY',
      quantity: '75.13',
      price: '120',
      instrument_name: 'SOL_USD',
      create_time: 2_000,
      update_time: 2_000,
    });
    const sellOpen = makeOrder({
      order_id: 'sell-open',
      side: 'SELL',
      quantity: '0.05',
      price: '140',
      instrument_name: 'SOL_USD',
      create_time: 3_000,
      update_time: 3_000,
    });

    const lots = rebuildOpenLots([sellClosed, buyCover, sellOpen]);

    expect(lots).toHaveLength(1);
    expect(lots[0].order.order_id).toBe('sell-open');
    expect(lots[0].remainingQty).toBeCloseTo(0.05);
    expect(lots[0].side).toBe('SELL');
  });

  it('nets duplicate closed sells so they are not marked open', () => {
    const sells = [1, 2, 3].map((n) =>
      makeOrder({
        order_id: `sell-dup-${n}`,
        side: 'SELL',
        quantity: '75.13',
        price: '137',
        instrument_name: 'SOL_USD',
        create_time: n * 1_000,
        update_time: n * 1_000,
      })
    );
    const covers = [1, 2, 3].map((n) =>
      makeOrder({
        order_id: `buy-dup-${n}`,
        side: 'BUY',
        quantity: '75.13',
        price: '130',
        instrument_name: 'SOL_USD',
        create_time: 10_000 + n * 1_000,
        update_time: 10_000 + n * 1_000,
      })
    );

    const lots = rebuildOpenLots([...sells, ...covers]);
    expect(lots).toHaveLength(0);
  });

  it('keeps only remaining short qty after partial cover', () => {
    const sell = makeOrder({
      order_id: 'sell-1',
      side: 'SELL',
      quantity: '1',
      price: '2000',
      create_time: 1_000,
      update_time: 1_000,
    });
    const buy = makeOrder({
      order_id: 'buy-1',
      side: 'BUY',
      quantity: '0.4',
      price: '1800',
      create_time: 2_000,
      update_time: 2_000,
    });

    const lots = rebuildOpenLots([sell, buy]);
    expect(lots).toHaveLength(1);
    expect(lots[0].side).toBe('SELL');
    expect(lots[0].remainingQty).toBeCloseTo(0.6);
  });

  it('trims open lots to the signed portfolio balance', () => {
    const sellA = makeOrder({
      order_id: 'sell-a',
      side: 'SELL',
      quantity: '1',
      price: '100',
      instrument_name: 'SOL_USD',
      create_time: 1_000,
      update_time: 1_000,
    });
    const sellB = makeOrder({
      order_id: 'sell-b',
      side: 'SELL',
      quantity: '1',
      price: '110',
      instrument_name: 'SOL_USD',
      create_time: 2_000,
      update_time: 2_000,
    });

    const open = rebuildOpenLots([sellA, sellB]);
    const trimmed = trimOpenLotsToBalance(open, -0.25);

    expect(trimmed).toHaveLength(1);
    expect(trimmed[0].order.order_id).toBe('sell-a');
    expect(trimmed[0].remainingQty).toBeCloseTo(0.25);
  });

  it('getOpenPositionLotsForAsset returns only lots for the current short balance', () => {
    const history = [
      makeOrder({
        order_id: 'sell-old',
        side: 'SELL',
        quantity: '75.13',
        price: '137',
        instrument_name: 'SOL_USD',
        create_time: 1_000,
        update_time: 1_000,
      }),
      makeOrder({
        order_id: 'buy-cover',
        side: 'BUY',
        quantity: '75.13',
        price: '120',
        instrument_name: 'SOL_USD',
        create_time: 2_000,
        update_time: 2_000,
      }),
      makeOrder({
        order_id: 'sell-open',
        side: 'SELL',
        quantity: '0.5',
        price: '140',
        instrument_name: 'SOL_USD',
        create_time: 3_000,
        update_time: 3_000,
      }),
    ];

    const lots = getOpenPositionLotsForAsset(history, 'SOL', -0.2);
    expect(lots).toHaveLength(1);
    expect(lots[0].order.order_id).toBe('sell-open');
    expect(lots[0].remainingQty).toBeCloseTo(0.2);
  });

  it('calculates unrealized P/L on remaining open qty only', () => {
    const sell = makeOrder({
      order_id: 'sell-1',
      side: 'SELL',
      quantity: '1',
      price: '100',
    });
    const lot = { order: sell, remainingQty: 0.25, side: 'SELL' as const };
    const result = calculateOpenLotProfitLoss(lot, 90);

    expect(result.available).toBe(true);
    expect(result.isRealized).toBe(false);
    expect(result.pnl).toBeCloseTo(2.5);
    expect(result.pnlPercent).toBeCloseTo(10);
  });
});
