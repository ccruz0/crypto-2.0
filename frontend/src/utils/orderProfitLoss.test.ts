import { describe, expect, it } from 'vitest';
import { OpenOrder } from '@/app/api';
import {
  buildOpenLotsByOrderId,
  buildRealizedPnlByOrderId,
  calculateOpenLotProfitLoss,
  calculateOpenLotsAggregateProfitLoss,
  calculateOrderProfitLoss,
  getExecutedOrderDisplayPnl,
  getOpenPositionLotsForAsset,
  getPnlUnavailableTooltip,
  isClosedExecutedEntryOrder,
  rebuildOpenLots,
  resolveCurrentPrice,
  trimOpenLotsToBalance,
} from './orderProfitLoss';
import type { TopCoin } from '@/app/api';

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
    expect(result.unavailableReason).toBe('closed_without_counterpart');
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

  it('aggregate asset P/L equals the sum of open-lot P/Ls (same mark)', () => {
    const mark = 64110;
    const lots = [
      {
        order: makeOrder({
          order_id: 'btc-1',
          side: 'BUY',
          quantity: '1.3',
          price: '58100',
          instrument_name: 'BTC_USD',
        }),
        remainingQty: 1.3,
        side: 'BUY' as const,
      },
      {
        order: makeOrder({
          order_id: 'btc-2',
          side: 'BUY',
          quantity: '0.3',
          price: '60500',
          instrument_name: 'BTC_USD',
        }),
        remainingQty: 0.3,
        side: 'BUY' as const,
      },
      {
        order: makeOrder({
          order_id: 'btc-3',
          side: 'BUY',
          quantity: '0.3',
          price: '63244.37',
          instrument_name: 'BTC_USD',
        }),
        remainingQty: 0.3,
        side: 'BUY' as const,
      },
      {
        order: makeOrder({
          order_id: 'btc-4',
          side: 'BUY',
          quantity: '0.297960',
          price: '71100',
          instrument_name: 'BTC_USD',
        }),
        remainingQty: 0.29796,
        side: 'BUY' as const,
      },
    ];

    const perLot = lots.map((lot) => calculateOpenLotProfitLoss(lot, mark));
    const sumPnl = perLot.reduce((acc, row) => acc + row.pnl, 0);
    const sumBasis = lots.reduce(
      (acc, lot) => acc + Number(lot.order.price) * lot.remainingQty,
      0
    );
    const aggregate = calculateOpenLotsAggregateProfitLoss(lots, mark);

    expect(aggregate.available).toBe(true);
    expect(aggregate.pnl).toBeCloseTo(sumPnl, 6);
    expect(aggregate.pnlPercent).toBeCloseTo((sumPnl / sumBasis) * 100, 6);
    // Must NOT collapse to a wrong backend-style avg that ignores lot entries.
    expect(aggregate.pnl).toBeGreaterThan(5000);
  });

  it('aggregate short P/L equals sum of open short lots', () => {
    const lots = [
      {
        order: makeOrder({ order_id: 's1', side: 'SELL', quantity: '2', price: '100' }),
        remainingQty: 1,
        side: 'SELL' as const,
      },
      {
        order: makeOrder({ order_id: 's2', side: 'SELL', quantity: '1', price: '110' }),
        remainingQty: 0.5,
        side: 'SELL' as const,
      },
    ];
    const mark = 90;
    const aggregate = calculateOpenLotsAggregateProfitLoss(lots, mark);
    const sum = lots.reduce((acc, lot) => acc + calculateOpenLotProfitLoss(lot, mark).pnl, 0);

    expect(aggregate.available).toBe(true);
    expect(aggregate.pnl).toBeCloseTo(sum);
    expect(aggregate.pnl).toBeCloseTo(20); // (100-90)*1 + (110-90)*0.5
  });
});

describe('getExecutedOrderDisplayPnl / Executed Orders tab', () => {
  it('shows unrealized long P/L for an open BUY vs mark price', () => {
    const buy = makeOrder({
      order_id: 'buy-open',
      side: 'BUY',
      quantity: '1',
      price: '100',
      instrument_name: 'ETH_USD',
    });
    const openLots = buildOpenLotsByOrderId([buy]);
    const result = getExecutedOrderDisplayPnl(buy, [buy], 110, openLots);

    expect(result.available).toBe(true);
    expect(result.isRealized).toBe(false);
    expect(result.pnl).toBeCloseTo(10);
    expect(result.pnlPercent).toBeCloseTo(10);
  });

  it('shows unrealized short P/L when price falls after open SELL', () => {
    const sell = makeOrder({
      order_id: 'sell-open',
      side: 'SELL',
      quantity: '1',
      price: '100',
      instrument_name: 'ETH_USD',
    });
    const openLots = buildOpenLotsByOrderId([sell]);
    const result = getExecutedOrderDisplayPnl(sell, [sell], 90, openLots);

    expect(result.available).toBe(true);
    expect(result.isRealized).toBe(false);
    expect(result.pnl).toBeCloseTo(10);
    expect(result.pnlPercent).toBeCloseTo(10);
  });

  it('shows realized long exit for a closed SELL matched to prior BUY', () => {
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
    const all = [buy, sell];
    const openLots = buildOpenLotsByOrderId(all);
    const realized = buildRealizedPnlByOrderId(all);
    expect(openLots.size).toBe(0);

    const result = getExecutedOrderDisplayPnl(sell, all, 130, openLots, realized);
    expect(result.available).toBe(true);
    expect(result.isRealized).toBe(true);
    expect(result.pnl).toBeCloseTo(20);
    expect(isClosedExecutedEntryOrder(sell, openLots, realized)).toBe(true);

    // Closed long entry BUY also shows the same FIFO realized P/L (orden cerrada).
    const buyResult = getExecutedOrderDisplayPnl(buy, all, 130, openLots, realized);
    expect(buyResult.available).toBe(true);
    expect(buyResult.isRealized).toBe(true);
    expect(buyResult.pnl).toBeCloseTo(20);
    expect(isClosedExecutedEntryOrder(buy, openLots, realized)).toBe(true);
  });

  it('FIFO-pairs partial qty and distant times for realized closed P/L', () => {
    // Proximity matcher fails: qty differs >20% and times are days apart.
    const buy = makeOrder({
      order_id: 'buy-big',
      side: 'BUY',
      quantity: '100',
      price: '0.10',
      instrument_name: 'DOGE_USD',
      create_time: 1_000,
      update_time: 1_000,
    });
    const sell = makeOrder({
      order_id: 'sell-half',
      side: 'SELL',
      quantity: '40',
      price: '0.12',
      instrument_name: 'DOGE_USD',
      create_time: 1_000 + 3 * 24 * 60 * 60 * 1000,
      update_time: 1_000 + 3 * 24 * 60 * 60 * 1000,
    });
    const all = [buy, sell];
    const openLots = buildOpenLotsByOrderId(all);
    const realized = buildRealizedPnlByOrderId(all);

    expect(openLots.has('buy-big')).toBe(true);
    expect(openLots.get('buy-big')?.remainingQty).toBeCloseTo(60);
    expect(openLots.has('sell-half')).toBe(false);

    const sellResult = getExecutedOrderDisplayPnl(sell, all, 0.11, openLots, realized);
    expect(sellResult.available).toBe(true);
    expect(sellResult.isRealized).toBe(true);
    expect(sellResult.pnl).toBeCloseTo((0.12 - 0.10) * 40);

    const buyOpen = getExecutedOrderDisplayPnl(buy, all, 0.11, openLots, realized);
    expect(buyOpen.available).toBe(true);
    expect(buyOpen.isRealized).toBe(false);
    expect(buyOpen.pnl).toBeCloseTo((0.11 - 0.10) * 60);
  });

  it('does not treat SL/TP protection fills as closed entry P/L', () => {
    const buy = makeOrder({
      order_id: 'buy-1',
      side: 'BUY',
      quantity: '1',
      price: '100',
      create_time: 1_000,
      update_time: 1_000,
    });
    const sl = makeOrder({
      order_id: 'sl-1',
      side: 'SELL',
      quantity: '1',
      price: '90',
      order_role: 'STOP_LOSS',
      order_type: 'STOP_LOSS',
      create_time: 10_000,
      update_time: 10_000,
    });
    const all = [buy, sl];
    const openLots = buildOpenLotsByOrderId(all);
    const realized = buildRealizedPnlByOrderId(all);

    // Protection order is excluded from FIFO; buy stays open.
    expect(openLots.has('buy-1')).toBe(true);
    expect(realized.has('sl-1')).toBe(false);

    const slResult = getExecutedOrderDisplayPnl(sl, all, 95, openLots, realized);
    expect(slResult.available).toBe(false);
    expect(isClosedExecutedEntryOrder(sl, openLots, realized)).toBe(false);
  });

  it('shows realized short cover for BUY that closes a prior SELL', () => {
    const sell = makeOrder({
      order_id: 'sell-1',
      side: 'SELL',
      quantity: '1',
      price: '120',
      create_time: 1_000,
      update_time: 1_000,
    });
    const buy = makeOrder({
      order_id: 'buy-cover',
      side: 'BUY',
      quantity: '1',
      price: '100',
      create_time: 10_000,
      update_time: 10_000,
    });
    const all = [sell, buy];
    const openLots = buildOpenLotsByOrderId(all);
    expect(openLots.size).toBe(0);

    const result = getExecutedOrderDisplayPnl(buy, all, 110, openLots);
    expect(result.available).toBe(true);
    expect(result.isRealized).toBe(true);
    expect(result.pnl).toBeCloseTo(20);
  });

  it('portfolio trim still applies when balances are passed (Portfolio path)', () => {
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
    const trimmedLots = buildOpenLotsByOrderId([sellA, sellB], [
      { coin: 'SOL', balance: -0.25 },
    ]);

    expect(trimmedLots.has('sell-a')).toBe(true);
    expect(trimmedLots.has('sell-b')).toBe(false);
    expect(trimmedLots.get('sell-a')?.remainingQty).toBeCloseTo(0.25);
  });

  it('Executed Orders ignores balance trim and marks all unmatched shorts', () => {
    // Mirrors DOGE_USD: exchange short balance may cover only older lots, but
    // Executed Orders still shows MTM for every unmatched SELL (no false "cerrada").
    const sellOldA = makeOrder({
      order_id: 'doge-sell-old-a',
      side: 'SELL',
      quantity: '135',
      price: '0.074',
      instrument_name: 'DOGE_USD',
      create_time: 1_000,
      update_time: 1_000,
    });
    const sellOldB = makeOrder({
      order_id: 'doge-sell-old-b',
      side: 'SELL',
      quantity: '133',
      price: '0.075',
      instrument_name: 'DOGE_USD',
      create_time: 2_000,
      update_time: 2_000,
    });
    const sellNew = makeOrder({
      order_id: 'doge-sell-new',
      side: 'SELL',
      quantity: '137',
      price: '0.0728',
      instrument_name: 'DOGE_USD',
      create_time: 3_000,
      update_time: 3_000,
    });
    const all = [sellOldA, sellOldB, sellNew];
    // No portfolio balances — Executed Orders path.
    const openLots = buildOpenLotsByOrderId(all);
    const realized = buildRealizedPnlByOrderId(all);
    const mark = 0.071;

    expect(openLots.has('doge-sell-old-a')).toBe(true);
    expect(openLots.has('doge-sell-old-b')).toBe(true);
    expect(openLots.has('doge-sell-new')).toBe(true);
    expect(realized.size).toBe(0);

    for (const sell of all) {
      const result = getExecutedOrderDisplayPnl(sell, all, mark, openLots, realized);
      expect(result.available).toBe(true);
      expect(result.isRealized).toBe(false);
      expect(isClosedExecutedEntryOrder(sell, openLots, realized)).toBe(false);
    }

    const newResult = getExecutedOrderDisplayPnl(sellNew, all, mark, openLots, realized);
    expect(newResult.pnl).toBeCloseTo((0.0728 - mark) * 137);
    expect(newResult.pnlPercent).toBeCloseTo(((0.0728 - mark) / 0.0728) * 100);
  });

  it('even if lots were balance-trimmed, orphan shorts get MTM not orden cerrada', () => {
    const sellOld = makeOrder({
      order_id: 'sell-kept',
      side: 'SELL',
      quantity: '100',
      price: '0.08',
      instrument_name: 'DOGE_USD',
      create_time: 1_000,
      update_time: 1_000,
    });
    const sellOrphan = makeOrder({
      order_id: 'sell-orphan',
      side: 'SELL',
      quantity: '137',
      price: '0.0728',
      instrument_name: 'DOGE_USD',
      create_time: 2_000,
      update_time: 2_000,
    });
    const all = [sellOld, sellOrphan];
    const trimmedLots = buildOpenLotsByOrderId(all, [{ coin: 'DOGE', balance: -100 }]);
    const realized = buildRealizedPnlByOrderId(all);
    const mark = 0.071;

    expect(trimmedLots.has('sell-orphan')).toBe(false);
    expect(realized.has('sell-orphan')).toBe(false);

    const result = getExecutedOrderDisplayPnl(
      sellOrphan,
      all,
      mark,
      trimmedLots,
      realized
    );
    expect(result.available).toBe(true);
    expect(result.isRealized).toBe(false);
    expect(result.pnl).toBeCloseTo((0.0728 - mark) * 137);
    expect(isClosedExecutedEntryOrder(sellOrphan, trimmedLots, realized)).toBe(false);
  });

  it('getPnlUnavailableTooltip explains closed_without_counterpart without claiming cerrada', () => {
    const tip = getPnlUnavailableTooltip('closed_without_counterpart');
    expect(tip).not.toMatch(/orden cerrada/i);
    expect(tip).toMatch(/historial/i);
  });

  it('resolveCurrentPrice matches instrument or base symbol', () => {
    const coins = [
      {
        rank: 1,
        instrument_name: 'ETH_USD',
        base_currency: 'ETH',
        quote_currency: 'USD',
        current_price: 1842.5,
        volume_24h: 1,
        updated_at: '',
      },
    ] as TopCoin[];

    expect(resolveCurrentPrice('ETH_USD', coins)).toBeCloseTo(1842.5);
    expect(resolveCurrentPrice('ETH_USDT', coins)).toBeCloseTo(1842.5);
    expect(resolveCurrentPrice('BTC_USD', coins)).toBeNull();
  });
});
