import { OpenOrder, TopCoin } from '@/app/api';

export interface OrderProfitLoss {
  pnl: number;
  pnlPercent: number;
  isRealized: boolean;
}

const PROTECTION_ROLES = new Set(['STOP_LOSS', 'TAKE_PROFIT']);
const TRIGGER_ORDER_TYPES = new Set([
  'STOP_LIMIT',
  'STOP_LOSS',
  'STOP_LOSS_LIMIT',
  'TAKE_PROFIT',
  'TAKE_PROFIT_LIMIT',
]);

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

export function calculateOrderProfitLoss(
  order: OpenOrder,
  allOrders: OpenOrder[],
  currentPrice?: number | null
): OrderProfitLoss {
  const orderSymbol = order.instrument_name;
  const orderSide = order.side?.toUpperCase();
  const orderPrice = getOrderPrice(order);
  const orderQuantity = getOrderQuantity(order);
  const orderTime = getOrderExecutionTime(order);

  if (orderSide === 'SELL' && orderPrice > 0 && orderQuantity > 0) {
    const TIME_WINDOW_MS = 5 * 60 * 1000;
    const VOLUME_TOLERANCE = 0.20;
    const orderCreateTime = order.create_time || orderTime;

    const allBuyOrders = allOrders.filter(
      (o) =>
        o.instrument_name === orderSymbol &&
        o.side?.toUpperCase() === 'BUY' &&
        o.status === 'FILLED'
    );

    if (allBuyOrders.length > 0) {
      let matchedBuyOrder: OpenOrder | null = null;

      const pairedBuyOrders = allBuyOrders.filter((buyOrder) => {
        const buyCreateTime = buyOrder.create_time || buyOrder.update_time || 0;
        return Math.abs(orderCreateTime - buyCreateTime) <= TIME_WINDOW_MS;
      });

      if (pairedBuyOrders.length > 0) {
        matchedBuyOrder = pairedBuyOrders.reduce((best, current) => {
          const bestQty = getOrderQuantity(best);
          const currentQty = getOrderQuantity(current);
          return Math.abs(currentQty - orderQuantity) < Math.abs(bestQty - orderQuantity)
            ? current
            : best;
        });
      } else {
        const similarVolumeBuyOrders = allBuyOrders
          .filter((buyOrder) => {
            const buyQty = getOrderQuantity(buyOrder);
            if (buyQty <= 0) return false;
            return Math.abs(buyQty - orderQuantity) / orderQuantity <= VOLUME_TOLERANCE;
          })
          .sort((a, b) => {
            const aTime = getOrderExecutionTime(a);
            const bTime = getOrderExecutionTime(b);
            if (aTime < orderTime && bTime >= orderTime) return -1;
            if (bTime < orderTime && aTime >= orderTime) return 1;
            if (aTime < orderTime && bTime < orderTime) return bTime - aTime;
            return aTime - bTime;
          });

        if (similarVolumeBuyOrders.length > 0) {
          matchedBuyOrder = similarVolumeBuyOrders[0];
        }
      }

      if (matchedBuyOrder) {
        const buyPrice = getOrderPrice(matchedBuyOrder);
        if (buyPrice > 0) {
          const pnl = orderPrice * orderQuantity - buyPrice * orderQuantity;
          const pnlPercent = ((orderPrice - buyPrice) / buyPrice) * 100;
          return { pnl, pnlPercent, isRealized: true };
        }
      }
    }
  } else if (orderSide === 'BUY' && orderPrice > 0 && orderQuantity > 0 && currentPrice && currentPrice > 0) {
    const pnl = (currentPrice - orderPrice) * orderQuantity;
    const pnlPercent = ((currentPrice - orderPrice) / orderPrice) * 100;
    return { pnl, pnlPercent, isRealized: false };
  }

  return { pnl: 0, pnlPercent: 0, isRealized: false };
}

export function filterFilledEntryOrdersForAsset(
  orders: OpenOrder[],
  assetCoin: string
): OpenOrder[] {
  return orders
    .filter((order) => orderMatchesAsset(order, assetCoin) && isFilledEntryOrder(order))
    .sort((a, b) => getOrderExecutionTime(b) - getOrderExecutionTime(a));
}
