import { describe, expect, it } from 'vitest';
import { OpenOrder } from '@/app/api';
import {
  buildOpenLotsByOrderId,
  buildRealizedPnlByOrderId,
  calculateOpenLotProfitLoss,
  calculateOpenLotsAggregateProfitLoss,
  calculateOrderProfitLoss,
  getExecutedOrderDisplayPnl,
  getOpenLotsEmptyMessage,
  getOpenPositionLotsForAsset,
  getOrderLifecycleRole,
  getPnlUnavailableTooltip,
  isClosedExecutedEntryOrder,
  isManualProtectedEntry,
  rebuildClassicResidualLots,
  rebuildOpenLots,
  resolveCurrentPrice,
  selectOpenLotsForPortfolioDisplay,
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
      execution_origin: 'ALERT',
      create_time: 1_000,
      update_time: 1_000,
    });
    const buyCover = makeOrder({
      order_id: 'buy-cover',
      side: 'BUY',
      quantity: '75.13',
      price: '120',
      instrument_name: 'SOL_USD',
      execution_origin: 'MANUAL',
      create_time: 2_000,
      update_time: 2_000,
    });
    const sellOpen = makeOrder({
      order_id: 'sell-open',
      side: 'SELL',
      quantity: '0.05',
      price: '140',
      instrument_name: 'SOL_USD',
      execution_origin: 'ALERT',
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
        execution_origin: 'ALERT',
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
        execution_origin: 'MANUAL',
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
      execution_origin: 'ALERT',
      create_time: 1_000,
      update_time: 1_000,
    });
    const buy = makeOrder({
      order_id: 'buy-1',
      side: 'BUY',
      quantity: '0.4',
      price: '1800',
      execution_origin: 'MANUAL',
      create_time: 2_000,
      update_time: 2_000,
    });

    const lots = rebuildOpenLots([sell, buy]);
    expect(lots).toHaveLength(1);
    expect(lots[0].side).toBe('SELL');
    expect(lots[0].remainingQty).toBeCloseTo(0.6);
  });

  it('does not let alert SELL close an alert BUY', () => {
    const buy = makeOrder({
      order_id: 'dot-buy',
      side: 'BUY',
      quantity: '11.72',
      price: '0.8526',
      instrument_name: 'DOT_USD',
      execution_origin: 'ALERT',
      create_time: 1_000,
      update_time: 1_000,
    });
    const sell = makeOrder({
      order_id: 'dot-sell-alert',
      side: 'SELL',
      quantity: '11.72',
      price: '0.88',
      instrument_name: 'DOT_USD',
      execution_origin: 'ALERT',
      create_time: 2_000,
      update_time: 2_000,
    });

    const lots = rebuildOpenLots([buy, sell]);
    expect(lots).toHaveLength(2);
    expect(lots.map((l) => l.order.order_id).sort()).toEqual(['dot-buy', 'dot-sell-alert']);
  });

  it('classifies MANUAL with linked TP/SL as entry; MANUAL flatten as close', () => {
    const withTp = makeOrder({
      order_id: 'm-tp',
      side: 'BUY',
      execution_origin: 'MANUAL',
      has_linked_tp: true,
    });
    const withSl = makeOrder({
      order_id: 'm-sl',
      side: 'BUY',
      execution_origin: 'MANUAL',
      has_linked_sl: true,
    });
    const flatten = makeOrder({
      order_id: 'm-flat',
      side: 'SELL',
      execution_origin: 'MANUAL',
      has_linked_tp: false,
      has_linked_sl: false,
    });
    const alert = makeOrder({
      order_id: 'a1',
      side: 'BUY',
      execution_origin: 'ALERT',
    });
    const stopLoss = makeOrder({
      order_id: 'sl1',
      side: 'SELL',
      execution_origin: 'STOP_LOSS',
      order_role: 'STOP_LOSS',
      order_type: 'STOP_LOSS',
    });
    const takeProfit = makeOrder({
      order_id: 'tp1',
      side: 'SELL',
      execution_origin: 'TAKE_PROFIT',
      order_role: 'TAKE_PROFIT',
      order_type: 'TAKE_PROFIT',
    });

    expect(isManualProtectedEntry(withTp)).toBe(true);
    expect(isManualProtectedEntry(withSl)).toBe(true);
    expect(isManualProtectedEntry(flatten)).toBe(false);
    expect(getOrderLifecycleRole(withTp)).toBe('entry');
    expect(getOrderLifecycleRole(withSl)).toBe('entry');
    expect(getOrderLifecycleRole(flatten)).toBe('close');
    expect(getOrderLifecycleRole(alert)).toBe('entry');
    expect(getOrderLifecycleRole(stopLoss)).toBe('close');
    expect(getOrderLifecycleRole(takeProfit)).toBe('close');
  });

  it('treats MANUAL buys with linked TP as open entries (not closes)', () => {
    // Mirrors BTC Portfolio bug: large MANUAL OTOCO buys were classified as
    // closes, so only the ALERT micro showed under "Rendimiento por lot abierto".
    const manualBig = makeOrder({
      order_id: 'btc-manual-1.3',
      side: 'BUY',
      quantity: '1.3',
      price: '59100',
      instrument_name: 'BTC_USD',
      execution_origin: 'MANUAL',
      type_display: 'LIMIT (Manual)',
      has_linked_tp: true,
      create_time: 1_000,
      update_time: 1_000,
    });
    const manualMid = makeOrder({
      order_id: 'btc-manual-0.3',
      side: 'BUY',
      quantity: '0.3',
      price: '60500',
      instrument_name: 'BTC_USD',
      execution_origin: 'MANUAL',
      type_display: 'MARKET (Manual)',
      has_linked_tp: true,
      create_time: 2_000,
      update_time: 2_000,
    });
    const alertMicro = makeOrder({
      order_id: 'btc-alert-micro',
      side: 'BUY',
      quantity: '0.00016',
      price: '62343.84',
      instrument_name: 'BTC_USD',
      execution_origin: 'ALERT',
      type_display: 'MARKET (Alerta)',
      has_linked_tp: true,
      create_time: 3_000,
      update_time: 3_000,
    });
    // MANUAL flatten without protection stays a close (must not become an entry).
    const manualClose = makeOrder({
      order_id: 'btc-manual-flat',
      side: 'SELL',
      quantity: '0.05',
      price: '64000',
      instrument_name: 'BTC_USD',
      execution_origin: 'MANUAL',
      type_display: 'MARKET (Manual)',
      has_linked_tp: false,
      create_time: 4_000,
      update_time: 4_000,
    });

    const history = [manualBig, manualMid, alertMicro, manualClose];
    const lots = getOpenPositionLotsForAsset(history, 'BTC', 1.55016);

    expect(lots.map((l) => l.order.order_id).sort()).toEqual([
      'btc-alert-micro',
      'btc-manual-0.3',
      'btc-manual-1.3',
    ]);
    const totalQty = lots.reduce((s, l) => s + l.remainingQty, 0);
    expect(totalQty).toBeCloseTo(1.55016, 8);
    expect(lots.find((l) => l.order.order_id === 'btc-manual-1.3')?.remainingQty).toBeCloseTo(1.25);
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
        execution_origin: 'ALERT',
        create_time: 1_000,
        update_time: 1_000,
      }),
      makeOrder({
        order_id: 'buy-cover',
        side: 'BUY',
        quantity: '75.13',
        price: '120',
        instrument_name: 'SOL_USD',
        execution_origin: 'MANUAL',
        create_time: 2_000,
        update_time: 2_000,
      }),
      makeOrder({
        order_id: 'sell-open',
        side: 'SELL',
        quantity: '0.5',
        price: '140',
        instrument_name: 'SOL_USD',
        execution_origin: 'ALERT',
        create_time: 3_000,
        update_time: 3_000,
      }),
    ];

    const lots = getOpenPositionLotsForAsset(history, 'SOL', -0.2);
    expect(lots).toHaveLength(1);
    expect(lots[0].order.order_id).toBe('sell-open');
    expect(lots[0].remainingQty).toBeCloseTo(0.2);
  });

  it('keeps opposite-side open lots when wallet balance is long (BTC shorts case)', () => {
    const longManual = makeOrder({
      order_id: 'btc-long',
      side: 'BUY',
      quantity: '2.19',
      price: '59100',
      instrument_name: 'BTC_USD',
      execution_origin: 'MANUAL',
      has_linked_tp: true,
      create_time: 1_000,
      update_time: 1_000,
    });
    const shortA = makeOrder({
      order_id: 'btc-short-a',
      side: 'SELL',
      quantity: '0.00015',
      price: '62700',
      instrument_name: 'BTC_USD',
      execution_origin: 'ALERT',
      has_linked_tp: true,
      create_time: 2_000,
      update_time: 2_000,
    });
    const shortB = makeOrder({
      order_id: 'btc-short-b',
      side: 'SELL',
      quantity: '0.00016',
      price: '62300',
      instrument_name: 'BTC_USD',
      execution_origin: 'ALERT',
      has_linked_tp: true,
      create_time: 3_000,
      update_time: 3_000,
    });

    const rebuilt = rebuildOpenLots([longManual, shortA, shortB]);
    const sameSideOnly = trimOpenLotsToBalance(rebuilt, 2.19);
    expect(sameSideOnly.every((l) => l.side === 'BUY')).toBe(true);
    expect(sameSideOnly).toHaveLength(1);

    const displayed = selectOpenLotsForPortfolioDisplay(rebuilt, 2.19);
    expect(displayed.map((l) => l.order.order_id).sort()).toEqual([
      'btc-long',
      'btc-short-a',
      'btc-short-b',
    ]);

    const viaAsset = getOpenPositionLotsForAsset(
      [longManual, shortA, shortB],
      'BTC',
      2.19
    );
    expect(viaAsset.filter((l) => l.side === 'SELL')).toHaveLength(2);
    expect(viaAsset.filter((l) => l.side === 'BUY')).toHaveLength(1);
  });

  it('keeps opposite-side open longs when wallet balance is short', () => {
    const shortAlert = makeOrder({
      order_id: 'eth-short',
      side: 'SELL',
      quantity: '0.1',
      price: '1800',
      instrument_name: 'ETH_USD',
      execution_origin: 'ALERT',
      has_linked_tp: true,
      create_time: 1_000,
      update_time: 1_000,
    });
    const longHedge = makeOrder({
      order_id: 'eth-long',
      side: 'BUY',
      quantity: '0.05',
      price: '1700',
      instrument_name: 'ETH_USD',
      execution_origin: 'MANUAL',
      has_linked_tp: true,
      create_time: 2_000,
      update_time: 2_000,
    });

    const lots = getOpenPositionLotsForAsset([shortAlert, longHedge], 'ETH', -0.1);
    expect(lots.map((l) => l.order.order_id).sort()).toEqual(['eth-long', 'eth-short']);
    expect(lots.find((l) => l.order.order_id === 'eth-short')?.remainingQty).toBeCloseTo(0.1);
  });

  it('falls back to classic residual FIFO for unprotected MANUAL shorts (DGB/AAVE case)', () => {
    // Lifecycle treats unprotected MANUAL as close → rebuildOpenLots empty.
    // Classic residual matches Expected TP uncovered short inventory.
    const sellEntry = makeOrder({
      order_id: 'dgb-manual-sell',
      side: 'SELL',
      quantity: '336730',
      price: '0.00611',
      instrument_name: 'DGB_USD',
      execution_origin: 'MANUAL',
      has_linked_tp: false,
      create_time: 1_000,
      update_time: 1_000,
    });
    const buyCoverA = makeOrder({
      order_id: 'dgb-buy-a',
      side: 'BUY',
      quantity: '2020',
      price: '0.00494',
      instrument_name: 'DGB_USD',
      execution_origin: 'MANUAL',
      has_linked_tp: false,
      create_time: 2_000,
      update_time: 2_000,
    });
    const buyCoverB = makeOrder({
      order_id: 'dgb-buy-b',
      side: 'BUY',
      quantity: '2010',
      price: '0.00497',
      instrument_name: 'DGB_USD',
      execution_origin: 'MANUAL',
      has_linked_tp: false,
      create_time: 3_000,
      update_time: 3_000,
    });
    const history = [sellEntry, buyCoverA, buyCoverB];

    expect(rebuildOpenLots(history)).toHaveLength(0);
    const classic = rebuildClassicResidualLots(history);
    expect(classic).toHaveLength(1);
    expect(classic[0].side).toBe('SELL');
    expect(classic[0].remainingQty).toBeCloseTo(332700);

    // Long dust wallet must still list the residual short (opposite side).
    const lots = getOpenPositionLotsForAsset(history, 'DGB', 4028.36);
    expect(lots).toHaveLength(1);
    expect(lots[0].order.order_id).toBe('dgb-manual-sell');
    expect(lots[0].remainingQty).toBeCloseTo(332700);
  });

  it('describes empty expand when balance/P&L exist but no open lots', () => {
    expect(
      getOpenLotsEmptyMessage({ balance: 4028, hasBackendPnl: true })
    ).toMatch(/precio medio del exchange/i);
    expect(
      getOpenLotsEmptyMessage({ balance: 1, hasBackendPnl: false })
    ).toMatch(/depósitos|sincronizado/i);
    expect(getOpenLotsEmptyMessage({ balance: 0 })).toMatch(/liquidado/i);
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
  it('prefers OTOCO parent_order_id over older FIFO buy (BTC 0.3 TP regression)', () => {
    // Mirrors production: TP 73817490102011214 linked to BUY @ 60500, but an
    // older protected BUY @ 71100 would steal the fill under pure FIFO → -7.20%.
    const olderWrongBuy = makeOrder({
      order_id: '5755600489289088548',
      side: 'BUY',
      quantity: '0.3',
      price: '71100',
      instrument_name: 'BTC_USD',
      order_type: 'MARKET',
      execution_origin: 'MANUAL',
      has_linked_tp: true,
      create_time: 1_000,
      update_time: 1_000,
    });
    const correctParentBuy = makeOrder({
      order_id: '5755600489811716124',
      side: 'BUY',
      quantity: '0.3',
      price: '60500',
      instrument_name: 'BTC_USD',
      order_type: 'MARKET',
      execution_origin: 'MANUAL',
      has_linked_tp: true,
      create_time: 2_000,
      update_time: 2_000,
    });
    const tp = makeOrder({
      order_id: '73817490102011214',
      side: 'SELL',
      quantity: '0.3',
      price: '65945',
      instrument_name: 'BTC_USD',
      order_type: 'TAKE_PROFIT_LIMIT',
      order_role: 'TAKE_PROFIT',
      execution_origin: 'TAKE_PROFIT',
      parent_order_id: '5755600489811716124',
      create_time: 3_000,
      update_time: 4_000,
    });
    const all = [olderWrongBuy, correctParentBuy, tp];
    const openLots = buildOpenLotsByOrderId(all);
    const realized = buildRealizedPnlByOrderId(all);

    const tpPnl = getExecutedOrderDisplayPnl(tp, all, 66000, openLots, realized);
    expect(tpPnl.available).toBe(true);
    expect(tpPnl.isRealized).toBe(true);
    expect(tpPnl.pnlPercent).toBeCloseTo(((65945 - 60500) / 60500) * 100); // +9.00%
    expect(tpPnl.pnl).toBeCloseTo((65945 - 60500) * 0.3);

    // Parent lot fully closed; older unrelated buy stays open.
    expect(openLots.has('5755600489811716124')).toBe(false);
    expect(openLots.has('5755600489289088548')).toBe(true);
    expect(realized.get('5755600489811716124')?.pnlPercent).toBeCloseTo(9);
    expect(realized.has('5755600489289088548')).toBe(false);
  });

  it('does not FIFO a parent-linked TP onto older lot after parent qty exhausted (BTC -8.30% regression)', () => {
    // Prod: alert BUY 0.00016 @ 62343.84; many TPs share the same parent_order_id.
    // First TP consumes the parent; later TP @ 65199.57 used to FIFO onto BUY @ 71100 → -8.30%.
    const olderWrongBuy = makeOrder({
      order_id: '5755600489289088548',
      side: 'BUY',
      quantity: '0.3',
      price: '71100',
      instrument_name: 'BTC_USD',
      order_type: 'MARKET',
      execution_origin: 'MANUAL',
      has_linked_tp: true,
      create_time: 1_000,
      update_time: 1_000,
    });
    const parentBuy = makeOrder({
      order_id: '5755600491541413116',
      side: 'BUY',
      quantity: '0.00016',
      price: '62343.84',
      instrument_name: 'BTC_USD',
      order_type: 'MARKET',
      execution_origin: 'ALERT',
      has_linked_tp: true,
      has_linked_sl: true,
      create_time: 2_000,
      update_time: 2_000,
    });
    const firstTp = makeOrder({
      order_id: '73817490101967200',
      side: 'SELL',
      quantity: '0.00016',
      price: '62967.28',
      instrument_name: 'BTC_USD',
      order_type: 'TAKE_PROFIT_LIMIT',
      order_role: 'TAKE_PROFIT',
      execution_origin: 'TAKE_PROFIT',
      parent_order_id: '5755600491541413116',
      create_time: 3_000,
      update_time: 3_500,
    });
    const laterTp = makeOrder({
      order_id: '73817490102011217',
      side: 'SELL',
      quantity: '0.00016',
      price: '65199.57',
      avg_price: '65239.32',
      instrument_name: 'BTC_USD',
      order_type: 'TAKE_PROFIT_LIMIT',
      order_role: 'TAKE_PROFIT',
      execution_origin: 'TAKE_PROFIT',
      parent_order_id: '5755600491541413116',
      create_time: 4_000,
      update_time: 5_000,
    });
    const all = [olderWrongBuy, parentBuy, firstTp, laterTp];
    const openLots = buildOpenLotsByOrderId(all);
    const realized = buildRealizedPnlByOrderId(all);

    // Older 71100 lot must stay fully open (not nibbled by orphan sibling TPs).
    expect(openLots.get('5755600489289088548')?.remainingQty).toBeCloseTo(0.3);
    expect(realized.has('5755600489289088548')).toBe(false);

    const laterPnl = getExecutedOrderDisplayPnl(laterTp, all, 65000, openLots, realized);
    expect(laterPnl.available).toBe(true);
    expect(laterPnl.isRealized).toBe(true);
    // Attribute to OTOCO parent, not FIFO @ 71100.
    expect(laterPnl.pnlPercent).toBeCloseTo(((65199.57 - 62343.84) / 62343.84) * 100); // +4.58%
    expect(laterPnl.pnlPercent).not.toBeCloseTo(((65199.57 - 71100) / 71100) * 100); // not -8.30%
  });

  it('shows unrealized long P/L for an open BUY vs mark price', () => {
    const buy = makeOrder({
      order_id: 'buy-open',
      side: 'BUY',
      quantity: '1',
      price: '100',
      instrument_name: 'ETH_USD',
      execution_origin: 'ALERT',
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
      execution_origin: 'ALERT',
    });
    const openLots = buildOpenLotsByOrderId([sell]);
    const result = getExecutedOrderDisplayPnl(sell, [sell], 90, openLots);

    expect(result.available).toBe(true);
    expect(result.isRealized).toBe(false);
    expect(result.pnl).toBeCloseTo(10);
    expect(result.pnlPercent).toBeCloseTo(10);
  });

  it('keeps alert BUY open when later alert SELL exists (no false orden cerrada)', () => {
    const buy = makeOrder({
      order_id: 'dot-buy',
      side: 'BUY',
      quantity: '11.72',
      price: '0.8526',
      instrument_name: 'DOT_USD',
      execution_origin: 'ALERT',
      create_time: 1_000,
      update_time: 1_000,
    });
    const sell = makeOrder({
      order_id: 'dot-sell',
      side: 'SELL',
      quantity: '11.5',
      price: '0.87',
      instrument_name: 'DOT_USD',
      execution_origin: 'ALERT',
      create_time: 2_000,
      update_time: 2_000,
    });
    const all = [buy, sell];
    const openLots = buildOpenLotsByOrderId(all);
    const realized = buildRealizedPnlByOrderId(all);
    const mark = 0.878;

    expect(openLots.has('dot-buy')).toBe(true);
    expect(openLots.has('dot-sell')).toBe(true);
    expect(realized.size).toBe(0);
    expect(isClosedExecutedEntryOrder(buy, openLots, realized)).toBe(false);

    const buyPnl = getExecutedOrderDisplayPnl(buy, all, mark, openLots, realized);
    expect(buyPnl.isRealized).toBe(false);
    expect(buyPnl.pnlPercent).toBeCloseTo(((mark - 0.8526) / 0.8526) * 100);
  });

  it('shows realized long exit only when MANUAL/SL/TP closes a prior alert BUY', () => {
    const buy = makeOrder({
      order_id: 'buy-1',
      side: 'BUY',
      quantity: '1',
      price: '100',
      execution_origin: 'ALERT',
      create_time: 1_000,
      update_time: 1_000,
    });
    const sell = makeOrder({
      order_id: 'sell-1',
      side: 'SELL',
      quantity: '1',
      price: '120',
      execution_origin: 'MANUAL',
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
    // Close leg is realized, but "orden cerrada" bold applies only to entries.
    expect(isClosedExecutedEntryOrder(sell, openLots, realized)).toBe(false);

    const buyResult = getExecutedOrderDisplayPnl(buy, all, 130, openLots, realized);
    expect(buyResult.available).toBe(true);
    expect(buyResult.isRealized).toBe(true);
    expect(buyResult.pnl).toBeCloseTo(20);
    expect(isClosedExecutedEntryOrder(buy, openLots, realized)).toBe(true);
  });

  it('FIFO-pairs partial qty and distant times for realized closed P/L', () => {
    const buy = makeOrder({
      order_id: 'buy-big',
      side: 'BUY',
      quantity: '100',
      price: '0.10',
      instrument_name: 'DOGE_USD',
      execution_origin: 'ALERT',
      create_time: 1_000,
      update_time: 1_000,
    });
    const sell = makeOrder({
      order_id: 'sell-half',
      side: 'SELL',
      quantity: '40',
      price: '0.12',
      instrument_name: 'DOGE_USD',
      execution_origin: 'MANUAL',
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

  it('closes alert BUY when SL/TP protection fill executes', () => {
    const buy = makeOrder({
      order_id: 'buy-1',
      side: 'BUY',
      quantity: '1',
      price: '100',
      execution_origin: 'ALERT',
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
      execution_origin: 'STOP_LOSS',
      create_time: 10_000,
      update_time: 10_000,
    });
    const all = [buy, sl];
    const openLots = buildOpenLotsByOrderId(all);
    const realized = buildRealizedPnlByOrderId(all);

    expect(openLots.has('buy-1')).toBe(false);
    expect(realized.has('sl-1')).toBe(true);
    expect(isClosedExecutedEntryOrder(buy, openLots, realized)).toBe(true);

    const slResult = getExecutedOrderDisplayPnl(sl, all, 95, openLots, realized);
    expect(slResult.available).toBe(true);
    expect(slResult.isRealized).toBe(true);
    expect(slResult.pnl).toBeCloseTo(-10);
    expect(isClosedExecutedEntryOrder(sl, openLots, realized)).toBe(false);
  });

  it('shows realized short cover for MANUAL BUY that closes a prior alert SELL', () => {
    const sell = makeOrder({
      order_id: 'sell-1',
      side: 'SELL',
      quantity: '1',
      price: '120',
      execution_origin: 'ALERT',
      create_time: 1_000,
      update_time: 1_000,
    });
    const buy = makeOrder({
      order_id: 'buy-cover',
      side: 'BUY',
      quantity: '1',
      price: '100',
      execution_origin: 'MANUAL',
      create_time: 10_000,
      update_time: 10_000,
    });
    const all = [sell, buy];
    const openLots = buildOpenLotsByOrderId(all);
    const realized = buildRealizedPnlByOrderId(all);
    expect(openLots.size).toBe(0);

    const result = getExecutedOrderDisplayPnl(buy, all, 110, openLots, realized);
    expect(result.available).toBe(true);
    expect(result.isRealized).toBe(true);
    expect(result.pnl).toBeCloseTo(20);
    expect(isClosedExecutedEntryOrder(sell, openLots, realized)).toBe(true);
  });

  it('portfolio trim still applies when balances are passed (Portfolio path)', () => {
    const sellA = makeOrder({
      order_id: 'sell-a',
      side: 'SELL',
      quantity: '1',
      price: '100',
      instrument_name: 'SOL_USD',
      execution_origin: 'ALERT',
      create_time: 1_000,
      update_time: 1_000,
    });
    const sellB = makeOrder({
      order_id: 'sell-b',
      side: 'SELL',
      quantity: '1',
      price: '110',
      instrument_name: 'SOL_USD',
      execution_origin: 'ALERT',
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
      execution_origin: 'ALERT',
      create_time: 1_000,
      update_time: 1_000,
    });
    const sellOldB = makeOrder({
      order_id: 'doge-sell-old-b',
      side: 'SELL',
      quantity: '133',
      price: '0.075',
      instrument_name: 'DOGE_USD',
      execution_origin: 'ALERT',
      create_time: 2_000,
      update_time: 2_000,
    });
    const sellNew = makeOrder({
      order_id: 'doge-sell-new',
      side: 'SELL',
      quantity: '137',
      price: '0.0728',
      instrument_name: 'DOGE_USD',
      execution_origin: 'ALERT',
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
      execution_origin: 'ALERT',
      create_time: 1_000,
      update_time: 1_000,
    });
    const sellOrphan = makeOrder({
      order_id: 'sell-orphan',
      side: 'SELL',
      quantity: '137',
      price: '0.0728',
      instrument_name: 'DOGE_USD',
      execution_origin: 'ALERT',
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
