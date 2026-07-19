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
const CLOSE_ORIGINS = new Set(['MANUAL', 'STOP_LOSS', 'TAKE_PROFIT', 'EXCHANGE']);
const ENTRY_ORIGINS = new Set(['ALERT']);

const TIME_WINDOW_MS = 5 * 60 * 1000;
const VOLUME_TOLERANCE = 0.20;
const QTY_EPS = 1e-12;

/** Position lifecycle: alert opens; only manual flatten / SL / TP close. */
export type OrderLifecycleRole = 'entry' | 'close';

/**
 * MANUAL fill that opened inventory with its own TP/SL (OTOCO), not a flatten.
 * These are real open lots (same as Expected TP), distinct from MANUAL closes.
 */
export function isManualProtectedEntry(order: OpenOrder): boolean {
  const origin = (order.execution_origin || '').toUpperCase();
  const typeDisplay = (order.type_display || order.execution_origin_label || '').toLowerCase();
  const looksManual = origin === 'MANUAL' || typeDisplay.includes('manual');
  if (!looksManual) return false;
  return order.has_linked_tp === true || order.has_linked_sl === true;
}

/**
 * Classify a fill as a position entry or a position close.
 *
 * Business rule:
 * - ALERT buy/sell → new entry (with its own SL/TP), never closes another alert
 * - MANUAL with linked TP/SL → entry (manual open with protection; real open lot)
 * - MANUAL flatten / SL / TP → close against opposite-side entry inventory
 * - Legacy fills without origin → entry (do not invent false closes)
 */
export function getOrderLifecycleRole(order: OpenOrder): OrderLifecycleRole | null {
  const status = (order.status || '').toUpperCase();
  const side = (order.side || '').toUpperCase();
  if (status !== 'FILLED') return null;
  if (side !== 'BUY' && side !== 'SELL') return null;

  const role = (order.order_role || '').toUpperCase();
  const orderType = (order.order_type || '').toUpperCase();
  const origin = (order.execution_origin || '').toUpperCase();

  if (PROTECTION_ROLES.has(role) || TRIGGER_ORDER_TYPES.has(orderType)) {
    return 'close';
  }
  // Manual opens with attached TP/SL are inventory entries (e.g. large BTC buys).
  if (isManualProtectedEntry(order)) {
    return 'entry';
  }
  if (CLOSE_ORIGINS.has(origin)) {
    return 'close';
  }
  if (ENTRY_ORIGINS.has(origin)) {
    return 'entry';
  }

  // type_display fallback when execution_origin is missing from older payloads
  const typeDisplay = (order.type_display || order.execution_origin_label || '').toLowerCase();
  if (typeDisplay.includes('sl ejecutado') || typeDisplay.includes('tp ejecutado')) {
    return 'close';
  }
  if (typeDisplay.includes('manual')) {
    return 'close';
  }
  if (typeDisplay.includes('alerta')) {
    return 'entry';
  }

  // Untagged filled market/limit: treat as entry so alert history cannot
  // false-close against other alerts via FIFO.
  return 'entry';
}

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
  return getOrderLifecycleRole(order) === 'entry';
}

export function isFilledCloseOrder(order: OpenOrder): boolean {
  return getOrderLifecycleRole(order) === 'close';
}

export function isFilledPositionOrder(order: OpenOrder): boolean {
  const role = getOrderLifecycleRole(order);
  return role === 'entry' || role === 'close';
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
 * Rebuild still-open entry lots.
 *
 * ALERT and MANUAL-with-TP/SL open inventory. Only MANUAL flatten / SL / TP
 * fills of the opposite side reduce that inventory (FIFO). Alert never closes alert.
 */
export function rebuildOpenLots(orders: OpenOrder[]): OpenPositionLot[] {
  const chronological = [...orders]
    .filter(isFilledPositionOrder)
    .sort((a, b) => getOrderExecutionTime(a) - getOrderExecutionTime(b));

  const entryBuys = chronological.filter(
    (o) => isFilledEntryOrder(o) && (o.side || '').toUpperCase() === 'BUY'
  );
  const entrySells = chronological.filter(
    (o) => isFilledEntryOrder(o) && (o.side || '').toUpperCase() === 'SELL'
  );
  const closeSells = chronological.filter(
    (o) => isFilledCloseOrder(o) && (o.side || '').toUpperCase() === 'SELL'
  );
  const closeBuys = chronological.filter(
    (o) => isFilledCloseOrder(o) && (o.side || '').toUpperCase() === 'BUY'
  );

  const closeSellRemaining = new Map<string, number>();
  closeSells.forEach((sell, index) => {
    const key = sell.order_id || `close-sell-${index}`;
    closeSellRemaining.set(key, getOrderQuantity(sell));
  });

  const closeBuyRemaining = new Map<string, number>();
  closeBuys.forEach((buy, index) => {
    const key = buy.order_id || `close-buy-${index}`;
    closeBuyRemaining.set(key, getOrderQuantity(buy));
  });

  const openLots: OpenPositionLot[] = [];

  for (const buy of entryBuys) {
    let remaining = getOrderQuantity(buy);
    const buyTime = getOrderExecutionTime(buy);
    for (let i = 0; i < closeSells.length; i++) {
      if (remaining <= QTY_EPS) break;
      const sell = closeSells[i];
      // SL/TP/manual must be after (or with) the entry they close.
      if (getOrderExecutionTime(sell) < buyTime) continue;
      const key = sell.order_id || `close-sell-${i}`;
      const sellQty = closeSellRemaining.get(key) ?? 0;
      if (sellQty <= QTY_EPS) continue;
      const applied = Math.min(remaining, sellQty);
      remaining -= applied;
      closeSellRemaining.set(key, sellQty - applied);
    }
    if (remaining > QTY_EPS && getOrderPrice(buy) > 0) {
      openLots.push({ order: buy, remainingQty: remaining, side: 'BUY' });
    }
  }

  for (const sell of entrySells) {
    let remaining = getOrderQuantity(sell);
    const sellTime = getOrderExecutionTime(sell);
    for (let i = 0; i < closeBuys.length; i++) {
      if (remaining <= QTY_EPS) break;
      const buy = closeBuys[i];
      if (getOrderExecutionTime(buy) < sellTime) continue;
      const key = buy.order_id || `close-buy-${i}`;
      const buyQty = closeBuyRemaining.get(key) ?? 0;
      if (buyQty <= QTY_EPS) continue;
      const applied = Math.min(remaining, buyQty);
      remaining -= applied;
      closeBuyRemaining.set(key, buyQty - applied);
    }
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
 *
 * Only keeps the side that matches the signed balance (BUY for long, SELL for
 * short). Prefer {@link selectOpenLotsForPortfolioDisplay} in Portfolio UI so
 * opposite-side open entries (hedges / micros with SL/TP) are not dropped.
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

/**
 * Portfolio expand display: trim same-side inventory to |balance| for P&L vs
 * wallet, but keep opposite-side open lots in full (e.g. long BTC balance must
 * still list micro SHORT alerts waiting on SL/TP).
 */
export function selectOpenLotsForPortfolioDisplay(
  lots: OpenPositionLot[],
  balance: number
): OpenPositionLot[] {
  const longs = lots.filter((lot) => lot.side === 'BUY');
  const shorts = lots.filter((lot) => lot.side === 'SELL');

  let selected: OpenPositionLot[];
  if (balance > QTY_EPS) {
    selected = [...trimOpenLotsToBalance(longs, balance), ...shorts];
  } else if (balance < -QTY_EPS) {
    selected = [...longs, ...trimOpenLotsToBalance(shorts, balance)];
  } else {
    // Flat wallet: still surface any rebuilt open entries (protected micros).
    selected = [...longs, ...shorts];
  }

  return selected.sort(
    (a, b) => getOrderExecutionTime(b.order) - getOrderExecutionTime(a.order)
  );
}

/**
 * Classic buy↔sell FIFO residual lots (Expected TP style).
 *
 * Used only when lifecycle {@link rebuildOpenLots} finds nothing — e.g.
 * unprotected MANUAL shorts that are still open on the book but classified as
 * closes under alert/manual lifecycle rules.
 */
export function rebuildClassicResidualLots(orders: OpenOrder[]): OpenPositionLot[] {
  const chronological = [...orders]
    .filter((o) => (o.status || '').toUpperCase() === 'FILLED')
    .filter((o) => {
      const side = (o.side || '').toUpperCase();
      return (side === 'BUY' || side === 'SELL') && getOrderQuantity(o) > QTY_EPS;
    })
    .sort((a, b) => getOrderExecutionTime(a) - getOrderExecutionTime(b));

  const buys = chronological.filter((o) => (o.side || '').toUpperCase() === 'BUY');
  const sells = chronological.filter((o) => (o.side || '').toUpperCase() === 'SELL');

  const sellRemaining = new Map<string, number>();
  sells.forEach((sell, index) => {
    sellRemaining.set(sell.order_id || `classic-sell-${index}`, getOrderQuantity(sell));
  });

  const lots: OpenPositionLot[] = [];

  for (const buy of buys) {
    let remaining = getOrderQuantity(buy);
    for (let i = 0; i < sells.length; i++) {
      if (remaining <= QTY_EPS) break;
      const sell = sells[i];
      const key = sell.order_id || `classic-sell-${i}`;
      const sellQty = sellRemaining.get(key) ?? 0;
      if (sellQty <= QTY_EPS) continue;
      const applied = Math.min(remaining, sellQty);
      remaining -= applied;
      sellRemaining.set(key, sellQty - applied);
    }
    if (remaining > QTY_EPS && getOrderPrice(buy) > 0) {
      lots.push({ order: buy, remainingQty: remaining, side: 'BUY' });
    }
  }

  for (let i = 0; i < sells.length; i++) {
    const sell = sells[i];
    const key = sell.order_id || `classic-sell-${i}`;
    const remaining = sellRemaining.get(key) ?? 0;
    if (remaining > QTY_EPS && getOrderPrice(sell) > 0) {
      lots.push({ order: sell, remainingQty: remaining, side: 'SELL' });
    }
  }

  return lots.sort(
    (a, b) => getOrderExecutionTime(b.order) - getOrderExecutionTime(a.order)
  );
}

export function getOpenPositionLotsForAsset(
  orders: OpenOrder[],
  assetCoin: string,
  balance: number
): OpenPositionLot[] {
  const filled = filterFilledPositionOrdersForAsset(orders, assetCoin);
  let openLots = rebuildOpenLots(filled);
  // Lifecycle rebuild empty (e.g. only unprotected MANUAL history) → classic
  // residual FIFO so Portfolio can still list inventory ETP already shows.
  if (openLots.length === 0) {
    openLots = rebuildClassicResidualLots(filled);
  }
  return selectOpenLotsForPortfolioDisplay(openLots, balance);
}

/** Spanish empty-state copy when expand has history but no displayable lots. */
export function getOpenLotsEmptyMessage(options: {
  balance: number;
  hasBackendPnl?: boolean;
}): string {
  const { balance, hasBackendPnl } = options;
  if (Math.abs(balance) > QTY_EPS && hasBackendPnl) {
    return (
      'No hay lots abiertos que coincidan con el historial de entradas. ' +
      'El P&L de la fila puede venir del precio medio del exchange (historial cerrado, ' +
      'depósitos o sync incompleto), no de lots con SL/TP abiertos.'
    );
  }
  if (Math.abs(balance) > QTY_EPS) {
    return (
      'No hay lots abiertos: el historial está liquidado o no encaja con el saldo actual. ' +
      'El saldo puede venir de depósitos, transferencias o historial no sincronizado.'
    );
  }
  return 'No hay lots abiertos: el historial está liquidado o no encaja con el saldo actual.';
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

export function filterFilledPositionOrdersForAsset(
  orders: OpenOrder[],
  assetCoin: string
): OpenOrder[] {
  return orders
    .filter((order) => orderMatchesAsset(order, assetCoin) && isFilledPositionOrder(order))
    .sort((a, b) => getOrderExecutionTime(b) - getOrderExecutionTime(a));
}

export interface PortfolioBalanceHint {
  coin: string;
  balance: number;
}

function groupFilledPositionOrdersBySymbol(orders: OpenOrder[]): Map<string, OpenOrder[]> {
  const bySymbol = new Map<string, OpenOrder[]>();
  for (const order of orders) {
    if (!isFilledPositionOrder(order)) continue;
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
 * When portfolio balances are provided, same-side lots are trimmed to |balance|
 * while opposite-side open lots are kept (Portfolio expand). Executed Orders
 * should call this without balances so every unmatched entry can still MTM.
 */
export function buildOpenLotsByOrderId(
  orders: OpenOrder[],
  portfolioAssets?: PortfolioBalanceHint[] | null
): Map<string, OpenPositionLot> {
  const bySymbol = groupFilledPositionOrdersBySymbol(orders);
  const map = new Map<string, OpenPositionLot>();

  for (const [symbol, symbolOrders] of bySymbol) {
    let lots = rebuildOpenLots(symbolOrders);
    if (lots.length === 0) {
      lots = rebuildClassicResidualLots(symbolOrders);
    }

    if (portfolioAssets && portfolioAssets.length > 0) {
      const base = getAssetBaseSymbol(symbol);
      const asset = portfolioAssets.find((a) => {
        const coin = (a.coin || '').toUpperCase();
        return coin === symbol || coin === base || getAssetBaseSymbol(coin) === base;
      });
      if (asset) {
        lots = selectOpenLotsForPortfolioDisplay(lots, asset.balance);
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
 * FIFO entry↔close pairing for realized P/L (same netting as rebuildOpenLots).
 * Alert never pairs with alert. Only MANUAL / SL / TP closes realize P/L.
 */
export function buildRealizedPnlByOrderId(orders: OpenOrder[]): Map<string, OrderProfitLoss> {
  const bySymbol = groupFilledPositionOrdersBySymbol(orders);
  const result = new Map<string, OrderProfitLoss>();

  for (const symbolOrders of bySymbol.values()) {
    const chronological = [...symbolOrders].sort(
      (a, b) => getOrderExecutionTime(a) - getOrderExecutionTime(b)
    );

    const entryBuys = chronological.filter(
      (o) => isFilledEntryOrder(o) && (o.side || '').toUpperCase() === 'BUY'
    );
    const entrySells = chronological.filter(
      (o) => isFilledEntryOrder(o) && (o.side || '').toUpperCase() === 'SELL'
    );
    const closeSells = chronological.filter(
      (o) => isFilledCloseOrder(o) && (o.side || '').toUpperCase() === 'SELL'
    );
    const closeBuys = chronological.filter(
      (o) => isFilledCloseOrder(o) && (o.side || '').toUpperCase() === 'BUY'
    );

    const closeSellRemaining = new Map<string, number>();
    closeSells.forEach((sell, index) => {
      const key = sell.order_id || `close-sell-${index}`;
      closeSellRemaining.set(key, getOrderQuantity(sell));
    });

    const closeBuyRemaining = new Map<string, number>();
    closeBuys.forEach((buy, index) => {
      const key = buy.order_id || `close-buy-${index}`;
      closeBuyRemaining.set(key, getOrderQuantity(buy));
    });

    const accum = new Map<string, RealizedAccum>();

    // Long exit: entry BUY closed by MANUAL/SL/TP SELL (close at/after entry)
    for (const buy of entryBuys) {
      let remaining = getOrderQuantity(buy);
      const buyPrice = getOrderPrice(buy);
      const buyId = buy.order_id || '';
      const buyTime = getOrderExecutionTime(buy);

      for (let i = 0; i < closeSells.length; i++) {
        if (remaining <= QTY_EPS) break;
        const sell = closeSells[i];
        if (getOrderExecutionTime(sell) < buyTime) continue;
        const key = sell.order_id || `close-sell-${i}`;
        const sellQty = closeSellRemaining.get(key) ?? 0;
        if (sellQty <= QTY_EPS) continue;

        const sellPrice = getOrderPrice(sell);
        const applied = Math.min(remaining, sellQty);
        remaining -= applied;
        closeSellRemaining.set(key, sellQty - applied);

        if (!(applied > QTY_EPS) || !(buyPrice > 0) || !(sellPrice > 0)) continue;

        const matchPnl = (sellPrice - buyPrice) * applied;
        const basis = buyPrice * applied;
        addRealized(accum, buyId, matchPnl, basis);
        addRealized(accum, sell.order_id || '', matchPnl, basis);
      }
    }

    // Short cover: entry SELL closed by MANUAL/SL/TP BUY (close at/after entry)
    for (const sell of entrySells) {
      let remaining = getOrderQuantity(sell);
      const sellPrice = getOrderPrice(sell);
      const sellId = sell.order_id || '';
      const sellTime = getOrderExecutionTime(sell);

      for (let i = 0; i < closeBuys.length; i++) {
        if (remaining <= QTY_EPS) break;
        const buy = closeBuys[i];
        if (getOrderExecutionTime(buy) < sellTime) continue;
        const key = buy.order_id || `close-buy-${i}`;
        const buyQty = closeBuyRemaining.get(key) ?? 0;
        if (buyQty <= QTY_EPS) continue;

        const buyPrice = getOrderPrice(buy);
        const applied = Math.min(remaining, buyQty);
        remaining -= applied;
        closeBuyRemaining.set(key, buyQty - applied);

        if (!(applied > QTY_EPS) || !(buyPrice > 0) || !(sellPrice > 0)) continue;

        const matchPnl = (sellPrice - buyPrice) * applied;
        const basis = sellPrice * applied;
        addRealized(accum, sellId, matchPnl, basis);
        addRealized(accum, buy.order_id || '', matchPnl, basis);
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
 * - Open alert entry lots → unrealized long/short vs mark
 * - Entry fully closed by MANUAL/SL/TP → realized ("orden cerrada")
 * - Close fill matched to an entry → realized
 * - Alert never realizes against another alert
 */
export function getExecutedOrderDisplayPnl(
  order: OpenOrder,
  allOrders: OpenOrder[],
  currentPrice: number | null | undefined,
  openLotsByOrderId: Map<string, OpenPositionLot>,
  realizedByOrderId?: Map<string, OrderProfitLoss>
): OrderProfitLoss {
  const lifecycle = getOrderLifecycleRole(order);
  if (!lifecycle) {
    return unavailable('invalid_order');
  }

  const orderId = order.order_id;
  if (lifecycle === 'entry' && orderId) {
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

  if (lifecycle === 'close') {
    // Unmatched manual/SL/TP: no inventada "orden cerrada" vs another alert.
    return unavailable('closed_without_counterpart');
  }

  // Open entry with no lot map hit: MTM vs mark.
  const side = (order.side || '').toUpperCase();
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
 * True only when a filled *entry* is fully closed by MANUAL/SL/TP with realized P/L.
 * Alert-vs-alert netting never qualifies. Balance-trimmed orphans are NOT closed.
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
      return 'No se pudo calcular el P&L (cantidad o precio inválidos)';
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
