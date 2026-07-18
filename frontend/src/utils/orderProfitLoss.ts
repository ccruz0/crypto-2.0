import { OpenOrder, TopCoin } from '@/app/api';

/** Why UI shows — when available is false. */
export type PnlUnavailableReason =
  | 'missing_mark_price'
  | 'closed_without_counterpart'
  | 'invalid_order';

export interface OrderProfitLoss {
  pnl: number;
  pnlPercent: number;
  isRealized: boolean;
  /** False when P/L could not be computed (UI should show —). */
  available: boolean;
  /** Set when available is false; drives Executed Orders tooltip copy. */
  unavailableReason?: PnlUnavailableReason;
}

export type PositionHint = 'LONG' | 'SHORT';

export interface CalculateOrderProfitLossOptions {
  /**
   * When SHORT, use short-open / short-cover semantics.
   * Portfolio rows with negative balance should pass SHORT.
   */
  positionHint?: PositionHint | null;
  /** When set, use this qty for P/L instead of the order's full filled qty. */
  openQty?: number | null;
}

/** One still-open inventory lot after FIFO netting of buys vs sells. */
export interface OpenPositionLot {
  order: OpenOrder;
  remainingQty: number;
  side: 'BUY' | 'SELL';
}

const PROTECTION_ROLES = new Set(['STOP_LOSS', 'TAKE_PROFIT']);
const TRIGGER_ORDER_TYPES = new Set([
  'STOP_LIMIT',
  'STOP_LOSS',
  'STOP_LOSS_LIMIT',
  'TAKE_PROFIT',
  'TAKE_PROFIT_LIMIT',
]);

const TIME_WINDOW_MS = 5 * 60 * 1000;
const VOLUME_TOLERANCE = 0.20;
const QTY_EPS = 1e-12;

function unavailable(reason: PnlUnavailableReason): OrderProfitLoss {
  return {
    pnl: 0,
    pnlPercent: 0,
    isRealized: false,
    available: false,
    unavailableReason: reason,
  };
}

export function getAssetBaseSymbol(coin: string | null | undefined): string {
  if (!coin) return '';
  return String(coin).split('_')[0].toUpperCase();
}

export function resolveInstrumentName(coin: string, topCoins?: TopCoin[]): string | null {
  const upper = coin.toUpperCase();
  if (upper.includes('_')) return upper;

  const base = getAssetBaseSymbol(upper);
  const match = topCoins?.find((c) => {
    const sym = (c.instrument_name || '').toUpperCase();
    return sym === upper || sym.startsWith(`${base}_`);
  });
  return match?.instrument_name?.toUpperCase() ?? null;
}

export function orderMatchesAsset(order: OpenOrder, assetCoin: string): boolean {
  const assetSymbol = assetCoin.toUpperCase();
  const assetBase = getAssetBaseSymbol(assetSymbol);
  const orderSymbol = (order.instrument_name || '').toUpperCase();
  const orderBase = getAssetBaseSymbol(orderSymbol);
  return orderSymbol === assetSymbol || orderBase === assetBase;
}

export function isFilledEntryOrder(order: OpenOrder): boolean {
  const status = (order.status || '').toUpperCase();
  const side = (order.side || '').toUpperCase();
  const role = (order.order_role || '').toUpperCase();
  if (status !== 'FILLED') return false;
  if (PROTECTION_ROLES.has(role)) return false;
  const orderType = (order.order_type || '').toUpperCase();
  if (TRIGGER_ORDER_TYPES.has(orderType)) return false;
  return side === 'BUY' || side === 'SELL';
}

export function getOrderQuantity(order: OpenOrder): number {
  return parseFloat(order.quantity || order.filled_quantity || order.cumulative_quantity || '0');
}

export function getOrderPrice(order: OpenOrder): number {
  return parseFloat(order.price || order.avg_price || order.filled_price || '0');
}

export function getOrderExecutionTime(order: OpenOrder): number {
  const raw = order.update_time || order.create_time || 0;
  return typeof raw === 'number' ? raw : new Date(raw).getTime();
}

function filterFilledSideOrders(
  orders: OpenOrder[],
  symbol: string,
  side: 'BUY' | 'SELL'
): OpenOrder[] {
  return orders.filter(
    (o) =>
      o.instrument_name === symbol &&
      o.side?.toUpperCase() === side &&
      (o.status || '').toUpperCase() === 'FILLED'
  );
}

/**
 * Match a counterpart order by creation-time proximity, else similar volume.
 * Prefer counterparts executed before `orderTime`.
 */
function findMatchedCounterpart(
  order: OpenOrder,
  counterparts: OpenOrder[]
): OpenOrder | null {
  if (counterparts.length === 0) return null;

  const orderQuantity = getOrderQuantity(order);
  const orderTime = getOrderExecutionTime(order);
  const orderCreateTime = order.create_time || orderTime;

  const paired = counterparts.filter((candidate) => {
    const candidateCreateTime = candidate.create_time || candidate.update_time || 0;
    return Math.abs(orderCreateTime - candidateCreateTime) <= TIME_WINDOW_MS;
  });

  if (paired.length > 0) {
    return paired.reduce((best, current) => {
      const bestQty = getOrderQuantity(best);
      const currentQty = getOrderQuantity(current);
      return Math.abs(currentQty - orderQuantity) < Math.abs(bestQty - orderQuantity)
        ? current
        : best;
    });
  }

  const similarVolume = counterparts
    .filter((candidate) => {
      const qty = getOrderQuantity(candidate);
      if (qty <= 0 || orderQuantity <= 0) return false;
      return Math.abs(qty - orderQuantity) / orderQuantity <= VOLUME_TOLERANCE;
    })
    .sort((a, b) => {
      const aTime = getOrderExecutionTime(a);
      const bTime = getOrderExecutionTime(b);
      if (aTime < orderTime && bTime >= orderTime) return -1;
      if (bTime < orderTime && aTime >= orderTime) return 1;
      if (aTime < orderTime && bTime < orderTime) return bTime - aTime;
      return aTime - bTime;
    });

  return similarVolume[0] ?? null;
}

function unrealizedShortPnl(
  sellPrice: number,
  quantity: number,
  currentPrice: number
): OrderProfitLoss {
  const pnl = (sellPrice - currentPrice) * quantity;
  const pnlPercent = ((sellPrice - currentPrice) / sellPrice) * 100;
  return { pnl, pnlPercent, isRealized: false, available: true };
}

function realizedShortCoverPnl(
  sellPrice: number,
  buyPrice: number,
  quantity: number
): OrderProfitLoss {
  const pnl = (sellPrice - buyPrice) * quantity;
  const pnlPercent = ((sellPrice - buyPrice) / sellPrice) * 100;
  return { pnl, pnlPercent, isRealized: true, available: true };
}

function realizedLongExitPnl(
  sellPrice: number,
  buyPrice: number,
  quantity: number
): OrderProfitLoss {
  const pnl = (sellPrice - buyPrice) * quantity;
  const pnlPercent = ((sellPrice - buyPrice) / buyPrice) * 100;
  return { pnl, pnlPercent, isRealized: true, available: true };
}

function unrealizedLongPnl(
  buyPrice: number,
  quantity: number,
  currentPrice: number
): OrderProfitLoss {
  const pnl = (currentPrice - buyPrice) * quantity;
  const pnlPercent = ((currentPrice - buyPrice) / buyPrice) * 100;
  return { pnl, pnlPercent, isRealized: false, available: true };
}

/**
 * Rebuild still-open lots with the same FIFO buy/sell netting used by the
 * backend Expected Take Profit path. Fully liquidated rounds drop out.
 */
export function rebuildOpenLots(orders: OpenOrder[]): OpenPositionLot[] {
  const chronological = [...orders]
    .filter(isFilledEntryOrder)
    .sort((a, b) => getOrderExecutionTime(a) - getOrderExecutionTime(b));

  const buys = chronological.filter((o) => (o.side || '').toUpperCase() === 'BUY');
  const sells = chronological.filter((o) => (o.side || '').toUpperCase() === 'SELL');

  const sellRemaining = new Map<string, number>();
  sells.forEach((sell, index) => {
    const key = sell.order_id || `sell-${index}`;
    sellRemaining.set(key, getOrderQuantity(sell));
  });

  const openLots: OpenPositionLot[] = [];

  for (const buy of buys) {
    let remaining = getOrderQuantity(buy);
    for (let i = 0; i < sells.length; i++) {
      if (remaining <= QTY_EPS) break;
      const sell = sells[i];
      const key = sell.order_id || `sell-${i}`;
      const sellQty = sellRemaining.get(key) ?? 0;
      if (sellQty <= QTY_EPS) continue;
      const applied = Math.min(remaining, sellQty);
      remaining -= applied;
      sellRemaining.set(key, sellQty - applied);
    }
    if (remaining > QTY_EPS && getOrderPrice(buy) > 0) {
      openLots.push({ order: buy, remainingQty: remaining, side: 'BUY' });
    }
  }

  for (let i = 0; i < sells.length; i++) {
    const sell = sells[i];
    const key = sell.order_id || `sell-${i}`;
    const remaining = sellRemaining.get(key) ?? 0;
    if (remaining > QTY_EPS && getOrderPrice(sell) > 0) {
      openLots.push({ order: sell, remainingQty: remaining, side: 'SELL' });
    }
  }

  return openLots.sort(
    (a, b) => getOrderExecutionTime(b.order) - getOrderExecutionTime(a.order)
  );
}

/**
 * Cap open lots so their remaining qty matches |balance|. Extra unmatched
 * history (incomplete sync / dust) is trimmed oldest-first.
 */
export function trimOpenLotsToBalance(
  lots: OpenPositionLot[],
  balance: number
): OpenPositionLot[] {
  const target = Math.abs(balance);
  if (!(target > QTY_EPS)) return [];

  const wantShort = balance < 0;
  const relevant = lots.filter((lot) => (wantShort ? lot.side === 'SELL' : lot.side === 'BUY'));
  // Oldest first so we keep the lots that FIFO would still consider open vs balance.
  const oldestFirst = [...relevant].sort(
    (a, b) => getOrderExecutionTime(a.order) - getOrderExecutionTime(b.order)
  );

  let need = target;
  const kept: OpenPositionLot[] = [];
  for (const lot of oldestFirst) {
    if (need <= QTY_EPS) break;
    const take = Math.min(lot.remainingQty, need);
    if (take > QTY_EPS) {
      kept.push({ ...lot, remainingQty: take });
      need -= take;
    }
  }

  return kept.sort(
    (a, b) => getOrderExecutionTime(b.order) - getOrderExecutionTime(a.order)
  );
}

export function getOpenPositionLotsForAsset(
  orders: OpenOrder[],
  assetCoin: string,
  balance: number
): OpenPositionLot[] {
  const filled = filterFilledEntryOrdersForAsset(orders, assetCoin);
  const openLots = rebuildOpenLots(filled);
  return trimOpenLotsToBalance(openLots, balance);
}

/** Unrealized P/L for a still-open lot vs mark price. */
export function calculateOpenLotProfitLoss(
  lot: OpenPositionLot,
  currentPrice?: number | null
): OrderProfitLoss {
  const entryPrice = getOrderPrice(lot.order);
  if (!(lot.remainingQty > QTY_EPS) || !(entryPrice > 0)) {
    return unavailable('invalid_order');
  }
  if (!(currentPrice && currentPrice > 0)) {
    return unavailable('missing_mark_price');
  }
  if (lot.side === 'SELL') {
    return unrealizedShortPnl(entryPrice, lot.remainingQty, currentPrice);
  }
  return unrealizedLongPnl(entryPrice, lot.remainingQty, currentPrice);
}

/**
 * Aggregate unrealized P/L across open lots — same formula and mark as each lot row.
 * Asset-level Net Profit / P&L % in Portfolio MUST equal this sum.
 *
 * Long:  Σ (mark − entry) * qty
 * Short: Σ (entry − mark) * qty
 * %:     total_pnl / Σ(entry * qty) * 100
 */
export function calculateOpenLotsAggregateProfitLoss(
  lots: OpenPositionLot[],
  currentPrice?: number | null
): OrderProfitLoss {
  if (!lots.length) {
    return unavailable('invalid_order');
  }
  if (!(currentPrice && currentPrice > 0)) {
    return unavailable('missing_mark_price');
  }

  let totalPnl = 0;
  let totalBasis = 0;
  let anyAvailable = false;

  for (const lot of lots) {
    const lotPnl = calculateOpenLotProfitLoss(lot, currentPrice);
    if (!lotPnl.available) continue;
    const entryPrice = getOrderPrice(lot.order);
    if (!(entryPrice > 0) || !(lot.remainingQty > QTY_EPS)) continue;
    totalPnl += lotPnl.pnl;
    totalBasis += entryPrice * lot.remainingQty;
    anyAvailable = true;
  }

  if (!anyAvailable || !(totalBasis > 0)) {
    return unavailable('invalid_order');
  }

  return {
    pnl: totalPnl,
    pnlPercent: (totalPnl / totalBasis) * 100,
    isRealized: false,
    available: true,
  };
}

export function calculateOrderProfitLoss(
  order: OpenOrder,
  allOrders: OpenOrder[],
  currentPrice?: number | null,
  options?: CalculateOrderProfitLossOptions
): OrderProfitLoss {
  const orderSymbol = order.instrument_name;
  const orderSide = order.side?.toUpperCase();
  const orderPrice = getOrderPrice(order);
  const orderQuantity =
    options?.openQty != null && options.openQty > 0
      ? options.openQty
      : getOrderQuantity(order);
  const positionHint = options?.positionHint ?? null;
  const isShortContext = positionHint === 'SHORT';

  if (orderSide === 'SELL' && orderPrice > 0 && orderQuantity > 0) {
    if (isShortContext) {
      if (currentPrice && currentPrice > 0) {
        return unrealizedShortPnl(orderPrice, orderQuantity, currentPrice);
      }
      return unavailable('missing_mark_price');
    }

    const matchedBuy = findMatchedCounterpart(
      order,
      filterFilledSideOrders(allOrders, orderSymbol, 'BUY')
    );
    if (matchedBuy) {
      const buyPrice = getOrderPrice(matchedBuy);
      if (buyPrice > 0) {
        return realizedLongExitPnl(orderPrice, buyPrice, orderQuantity);
      }
    }

    return unavailable('closed_without_counterpart');
  }

  if (orderSide === 'BUY' && orderPrice > 0 && orderQuantity > 0) {
    if (isShortContext) {
      const matchedSell = findMatchedCounterpart(
        order,
        filterFilledSideOrders(allOrders, orderSymbol, 'SELL')
      );
      if (matchedSell) {
        const sellPrice = getOrderPrice(matchedSell);
        if (sellPrice > 0) {
          return realizedShortCoverPnl(sellPrice, orderPrice, orderQuantity);
        }
      }
      return unavailable('closed_without_counterpart');
    }

    if (currentPrice && currentPrice > 0) {
      return unrealizedLongPnl(orderPrice, orderQuantity, currentPrice);
    }
    return unavailable('missing_mark_price');
  }

  return unavailable('invalid_order');
}

export function filterFilledEntryOrdersForAsset(
  orders: OpenOrder[],
  assetCoin: string
): OpenOrder[] {
  return orders
    .filter((order) => orderMatchesAsset(order, assetCoin) && isFilledEntryOrder(order))
    .sort((a, b) => getOrderExecutionTime(b) - getOrderExecutionTime(a));
}

export interface PortfolioBalanceHint {
  coin: string;
  balance: number;
}

function groupFilledEntryOrdersBySymbol(orders: OpenOrder[]): Map<string, OpenOrder[]> {
  const bySymbol = new Map<string, OpenOrder[]>();
  for (const order of orders) {
    if (!isFilledEntryOrder(order)) continue;
    const symbol = (order.instrument_name || '').toUpperCase();
    if (!symbol) continue;
    const list = bySymbol.get(symbol) ?? [];
    list.push(order);
    bySymbol.set(symbol, list);
  }
  return bySymbol;
}

/**
 * Index still-open FIFO lots by order_id across all symbols.
 *
 * When portfolio balances are provided, lots are trimmed to match |balance|
 * — use that only for Portfolio asset expansion. Executed Orders should call
 * this without balances so every unmatched entry can still mark-to-market.
 */
export function buildOpenLotsByOrderId(
  orders: OpenOrder[],
  portfolioAssets?: PortfolioBalanceHint[] | null
): Map<string, OpenPositionLot> {
  const bySymbol = groupFilledEntryOrdersBySymbol(orders);
  const map = new Map<string, OpenPositionLot>();

  for (const [symbol, symbolOrders] of bySymbol) {
    let lots = rebuildOpenLots(symbolOrders);

    if (portfolioAssets && portfolioAssets.length > 0) {
      const base = getAssetBaseSymbol(symbol);
      const asset = portfolioAssets.find((a) => {
        const coin = (a.coin || '').toUpperCase();
        return coin === symbol || coin === base || getAssetBaseSymbol(coin) === base;
      });
      if (asset) {
        lots = trimOpenLotsToBalance(lots, asset.balance);
      }
    }

    for (const lot of lots) {
      const id = lot.order.order_id;
      if (id) map.set(id, lot);
    }
  }

  return map;
}

interface RealizedAccum {
  pnl: number;
  /** Notional used for % (buy notional for long exits; sell notional for short covers). */
  basis: number;
}

function addRealized(accum: Map<string, RealizedAccum>, orderId: string, pnl: number, basis: number) {
  if (!orderId || !(basis > 0)) return;
  const prev = accum.get(orderId) ?? { pnl: 0, basis: 0 };
  prev.pnl += pnl;
  prev.basis += basis;
  accum.set(orderId, prev);
}

/**
 * FIFO buy↔sell pairing for realized P/L (same netting as rebuildOpenLots).
 * Attributes matched quantity to both legs so closed entries and exits both
 * show realized P/L — including partial fills and matches outside the 5‑min window.
 * SL/TP protection orders are excluded via isFilledEntryOrder.
 */
export function buildRealizedPnlByOrderId(orders: OpenOrder[]): Map<string, OrderProfitLoss> {
  const bySymbol = groupFilledEntryOrdersBySymbol(orders);
  const result = new Map<string, OrderProfitLoss>();

  for (const symbolOrders of bySymbol.values()) {
    const chronological = [...symbolOrders].sort(
      (a, b) => getOrderExecutionTime(a) - getOrderExecutionTime(b)
    );
    const buys = chronological.filter((o) => (o.side || '').toUpperCase() === 'BUY');
    const sells = chronological.filter((o) => (o.side || '').toUpperCase() === 'SELL');

    const sellRemaining = new Map<string, number>();
    sells.forEach((sell, index) => {
      const key = sell.order_id || `sell-${index}`;
      sellRemaining.set(key, getOrderQuantity(sell));
    });

    const accum = new Map<string, RealizedAccum>();

    for (const buy of buys) {
      let remaining = getOrderQuantity(buy);
      const buyPrice = getOrderPrice(buy);
      const buyId = buy.order_id || '';
      const buyTime = getOrderExecutionTime(buy);

      for (let i = 0; i < sells.length; i++) {
        if (remaining <= QTY_EPS) break;
        const sell = sells[i];
        const key = sell.order_id || `sell-${i}`;
        const sellQty = sellRemaining.get(key) ?? 0;
        if (sellQty <= QTY_EPS) continue;

        const sellPrice = getOrderPrice(sell);
        const applied = Math.min(remaining, sellQty);
        remaining -= applied;
        sellRemaining.set(key, sellQty - applied);

        if (!(applied > QTY_EPS) || !(buyPrice > 0) || !(sellPrice > 0)) continue;

        const matchPnl = (sellPrice - buyPrice) * applied;
        const sellTime = getOrderExecutionTime(sell);
        const sellId = sell.order_id || '';
        // Short cover: sell opened before buy. Long exit: buy first (or same time).
        const isShortCover = sellTime < buyTime;
        const basis = (isShortCover ? sellPrice : buyPrice) * applied;

        addRealized(accum, buyId, matchPnl, basis);
        addRealized(accum, sellId, matchPnl, basis);
      }
    }

    for (const [orderId, { pnl, basis }] of accum) {
      if (!(basis > 0)) continue;
      result.set(orderId, {
        pnl,
        pnlPercent: (pnl / basis) * 100,
        isRealized: true,
        available: true,
      });
    }
  }

  return result;
}

/**
 * P/L for a row on the Executed Orders tab:
 * - Still-open FIFO lots → unrealized long/short vs mark price
 * - Fully FIFO-paired (no open remainder) → realized buy↔sell P/L
 * - Unmatched remainder / no counterpart → MTM vs mark (never claim "cerrada")
 *
 * Balance trim is intentionally ignored here; callers should build openLots
 * without portfolio balances. Trim remains Portfolio-only.
 */
export function getExecutedOrderDisplayPnl(
  order: OpenOrder,
  allOrders: OpenOrder[],
  currentPrice: number | null | undefined,
  openLotsByOrderId: Map<string, OpenPositionLot>,
  realizedByOrderId?: Map<string, OrderProfitLoss>
): OrderProfitLoss {
  // SL/TP and other non-entry fills: never treat as open-lot / orden cerrada P/L.
  if (!isFilledEntryOrder(order)) {
    return unavailable('invalid_order');
  }

  const orderId = order.order_id;
  if (orderId) {
    const openLot = openLotsByOrderId.get(orderId);
    if (openLot) {
      return calculateOpenLotProfitLoss(openLot, currentPrice);
    }
  }

  const realizedMap = realizedByOrderId ?? buildRealizedPnlByOrderId(allOrders);
  if (orderId) {
    const realized = realizedMap.get(orderId);
    if (realized) return realized;
  }

  // Legacy proximity/volume match (same-symbol history gaps) before MTM fallback.
  const side = (order.side || '').toUpperCase();
  if (side === 'SELL') {
    const legacy = calculateOrderProfitLoss(order, allOrders, currentPrice, {
      positionHint: 'LONG',
    });
    if (legacy.available && legacy.isRealized) return legacy;
  } else if (side === 'BUY') {
    const buyTime = getOrderExecutionTime(order);
    const hasPriorSell = allOrders.some(
      (o) =>
        o.instrument_name === order.instrument_name &&
        (o.side || '').toUpperCase() === 'SELL' &&
        (o.status || '').toUpperCase() === 'FILLED' &&
        !PROTECTION_ROLES.has((o.order_role || '').toUpperCase()) &&
        getOrderExecutionTime(o) < buyTime
    );
    if (hasPriorSell) {
      const legacy = calculateOrderProfitLoss(order, allOrders, currentPrice, {
        positionHint: 'SHORT',
      });
      if (legacy.available && legacy.isRealized) return legacy;
    }
  }

  // No FIFO/legacy pair: still show unrealized MTM so every market entry has a %.
  const orderPrice = getOrderPrice(order);
  const orderQuantity = getOrderQuantity(order);
  if (!(orderPrice > 0) || !(orderQuantity > 0)) {
    return unavailable('invalid_order');
  }
  if (!(currentPrice && currentPrice > 0)) {
    return unavailable('missing_mark_price');
  }
  if (side === 'SELL') {
    return unrealizedShortPnl(orderPrice, orderQuantity, currentPrice);
  }
  if (side === 'BUY') {
    return unrealizedLongPnl(orderPrice, orderQuantity, currentPrice);
  }
  return unavailable('invalid_order');
}

/**
 * True only when a filled entry is fully FIFO-closed with numeric realized P/L.
 * Balance-trimmed orphans (no counterpart) are NOT closed.
 */
export function isClosedExecutedEntryOrder(
  order: OpenOrder,
  openLotsByOrderId: Map<string, OpenPositionLot>,
  realizedByOrderId?: Map<string, OrderProfitLoss>
): boolean {
  if (!isFilledEntryOrder(order)) return false;
  const orderId = order.order_id;
  if (!orderId) return false;
  if (openLotsByOrderId.has(orderId)) return false;
  const realized = realizedByOrderId?.get(orderId);
  return !!(realized?.available && realized.isRealized);
}

/** Spanish tooltip when Executed Orders shows — for P&L. */
export function getPnlUnavailableTooltip(reason?: PnlUnavailableReason): string {
  switch (reason) {
    case 'missing_mark_price':
      return 'Sin precio de mercado actual para calcular el P&L no realizado';
    case 'closed_without_counterpart':
      return (
        'Fuera del inventario abierto o sin compra/venta de cierre en el historial ' +
        'para calcular el P&L realizado (historial incompleto o posición no cubierta)'
      );
    case 'invalid_order':
      return 'No se pudo calcular el P&L (cantidad o precio inválidos, o orden de protección SL/TP)';
    default:
      return 'No se pudo calcular el P&L';
  }
}

/** Resolve mark price from watchlist/topCoins by instrument or base asset. */
export function resolveCurrentPrice(
  instrumentName: string | null | undefined,
  topCoins?: TopCoin[] | null
): number | null {
  if (!instrumentName || !topCoins?.length) return null;
  const upper = instrumentName.toUpperCase();
  const base = getAssetBaseSymbol(upper);

  const exact = topCoins.find((c) => (c.instrument_name || '').toUpperCase() === upper);
  if (exact?.current_price && exact.current_price > 0) return exact.current_price;

  const byBase = topCoins.find((c) => {
    const sym = (c.instrument_name || '').toUpperCase();
    return getAssetBaseSymbol(sym) === base && c.current_price > 0;
  });
  return byBase?.current_price && byBase.current_price > 0 ? byBase.current_price : null;
}
