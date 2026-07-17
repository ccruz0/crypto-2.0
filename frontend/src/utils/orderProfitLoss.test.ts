import { describe, expect, it } from 'vitest';
import { OpenOrder } from '@/app/api';
import { calculateOrderProfitLoss } from './orderProfitLoss';

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
    expect(result.pnlPercent).toBeCloseTo(((1876.73 - currentPrice) / 1876.73) * 100, 4);
  });

  it('computes realized short cover when BUY matches prior SELL', () => {
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
      quantity: '1',
      price: '1800',
      create_time: 10_000,
      update_time: 10_000,
    });

    const result = calculateOrderProfitLoss(buy, [sell, buy], null, {
      positionHint: 'SHORT',
    });

    expect(result.available).toBe(true);
    expect(result.isRealized).toBe(true);
    expect(result.pnl).toBeCloseTo(200);
    expect(result.pnlPercent).toBeCloseTo(10);
  });

  it('does not mark-to-market unmatched BUY in short context', () => {
    const buy = makeOrder({
      order_id: 'buy-1',
      side: 'BUY',
      quantity: '1',
      price: '1800',
    });

    const result = calculateOrderProfitLoss(buy, [buy], 1700, {
      positionHint: 'SHORT',
    });

    expect(result.available).toBe(false);
  });

  it('shows short loss when price rises after SELL', () => {
    const sell = makeOrder({
      order_id: 'sell-1',
      side: 'SELL',
      quantity: '2',
      price: '100',
    });

    const result = calculateOrderProfitLoss(sell, [sell], 110, {
      positionHint: 'SHORT',
    });

    expect(result.available).toBe(true);
    expect(result.pnl).toBeCloseTo(-20);
    expect(result.pnlPercent).toBeCloseTo(-10);
  });
});
