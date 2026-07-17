import { OpenOrder, TopCoin } from '@/app/api';

export interface OrderProfitLoss {
  pnl: number;
  pnlPercent: number;
  isRealized: boolean;
  /** False when P/L could not be computed (UI should show —). */
  available: boolean;
}

export type PositionHint = 'LONG' | 'SHORT';

export interface CalculateOrderProfitLossOptions {
  /**
   * When SHORT, use short-open / short-cover semantics.
   * Portfolio rows with negative balance should pass SHORT.
   */
  positionHint?: PositionHint | null;
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

const UNAVAILABLE_PNL: OrderProfitLoss = {
  pnl: 0,
  pnlPercent: 0,
  isRealized: false,
  available: false,
};

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

export function calculateOrderProfitLoss(
  order: OpenOrder,
  allOrders: OpenOrder[],
  currentPrice?: number | null,
  options?: CalculateOrderProfitLossOptions
): OrderProfitLoss {
  const orderSymbol = order.instrument_name;
  const orderSide = order.side?.toUpperCase();
  const orderPrice = getOrderPrice(order);
  const orderQuantity = getOrderQuantity(order);
  const positionHint = options?.positionHint ?? null;
  const isShortContext = positionHint === 'SHORT';

  if (orderSide === 'SELL' && orderPrice > 0 && orderQuantity > 0) {
    if (isShortContext) {
      // Open / add short: mark-to-market vs current price.
      if (currentPrice && currentPrice > 0) {
        return unrealizedShortPnl(orderPrice, orderQuantity, currentPrice);
      }
      return UNAVAILABLE_PNL;
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

    return UNAVAILABLE_PNL;
  }

  if (orderSide === 'BUY' && orderPrice > 0 && orderQuantity > 0) {
    if (isShortContext) {
      // Cover short: pair with a prior/similar SELL.
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
      return UNAVAILABLE_PNL;
    }

    if (currentPrice && currentPrice > 0) {
      return unrealizedLongPnl(orderPrice, orderQuantity, currentPrice);
    }
  }

  return UNAVAILABLE_PNL;
}

export function filterFilledEntryOrdersForAsset(
  orders: OpenOrder[],
  assetCoin: string
): OpenOrder[] {
  return orders
    .filter((order) => orderMatchesAsset(order, assetCoin) && isFilledEntryOrder(order))
    .sort((a, b) => getOrderExecutionTime(b) - getOrderExecutionTime(a));
}
