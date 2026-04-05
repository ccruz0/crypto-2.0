/**
 * Order transformation and utility functions
 */

import { UnifiedOpenOrder, OpenPosition, PortfolioAsset } from '@/app/api';

/**
 * Transform UnifiedOpenOrder[] to OpenPosition[]
 */
export function transformOrdersToPositions(orders: UnifiedOpenOrder[], portfolioAssets?: PortfolioAsset[]): OpenPosition[] {
  // Group orders by symbol and client_oid to find related orders
  const positionsMap = new Map<string, OpenPosition>();
  
  if (!orders || orders.length === 0) {
    // Silently return empty array if no orders (normal condition)
    return [];
  }
  
  // First pass: group SELL orders by symbol and client_oid (to find related TP/SL orders)
  const sellOrdersByClientOid = new Map<string, UnifiedOpenOrder[]>();
  
  orders.forEach(order => {
    if (order.side === 'SELL') {
      const clientOid = order.client_oid || `standalone-${order.order_id}`;
      if (!sellOrdersByClientOid.has(clientOid)) {
        sellOrdersByClientOid.set(clientOid, []);
      }
      sellOrdersByClientOid.get(clientOid)!.push(order);
    }
  });
  
  // Second pass: create positions from grouped SELL orders
  sellOrdersByClientOid.forEach((sellOrders, clientOid) => {
    if (sellOrders.length === 0) return;
    
    // All orders should have the same symbol (they're related)
    const symbol = sellOrders[0].symbol;
    
    // Calculate totals for SELL orders (TP/SL)
    const totalQuantity = sellOrders.reduce((sum, o) => sum + (o.quantity || 0), 0);
    const totalValue = sellOrders.reduce((sum, o) => sum + ((o.quantity || 0) * (o.price || 0)), 0);
    const avgPrice = totalQuantity > 0 ? totalValue / totalQuantity : null;
    
    // Count TP and SL orders and find limit prices
    const tpOrders = sellOrders.filter(o => 
      o.order_type === 'TAKE_PROFIT_LIMIT' || 
      o.order_type === 'TAKE_PROFIT' ||
      (o.is_trigger && o.trigger_type === 'TAKE_PROFIT')
    );
    const slOrders = sellOrders.filter(o => 
      o.order_type === 'STOP_LOSS_LIMIT' || 
      o.order_type === 'STOP_LOSS' ||
      (o.is_trigger && o.trigger_type === 'STOP_LOSS')
    );
    
    // Find TP price (highest limit price from TP orders)
    const tpPrices = tpOrders
      .map(o => o.price)
      .filter((p): p is number => p !== null && p !== undefined && p > 0);
    const tpPrice = tpPrices.length > 0 ? Math.max(...tpPrices) : null;
    
    // Find SL price (lowest limit price from SL orders)
    const slPrices = slOrders
      .map(o => o.price)
      .filter((p): p is number => p !== null && p !== undefined && p > 0);
    const slPrice = slPrices.length > 0 ? Math.min(...slPrices) : null;
    
    // Get entry price from portfolio if available, otherwise use avgPrice from orders
    let entryPrice: number | null = null;
    let entryQuantity: number = totalQuantity;
    
    if (portfolioAssets && portfolioAssets.length > 0) {
      // Try to find matching asset in portfolio
      const portfolioAsset = portfolioAssets.find(asset => 
        asset.coin === symbol || asset.coin === symbol.split('_')[0]
      );
      
      if (portfolioAsset && portfolioAsset.balance > 0 && portfolioAsset.value_usd > 0) {
        // Calculate entry price from portfolio: value_usd / balance
        entryPrice = portfolioAsset.value_usd / portfolioAsset.balance;
        entryQuantity = portfolioAsset.balance;
      }
    }
    
    // Fallback to avgPrice if portfolio data not available
    if (entryPrice === null) {
      entryPrice = avgPrice;
    }
    
    // Calculate TP/SL profits
    let tpProfit: number | null = null;
    let slProfit: number | null = null;
    
    if (entryPrice !== null && entryQuantity > 0) {
      if (tpPrice !== null) {
        // Profit = (TP price * quantity) - (entry price * quantity)
        tpProfit = (tpPrice * entryQuantity) - (entryPrice * entryQuantity);
      }
      if (slPrice !== null) {
        // Loss = (SL price * quantity) - (entry price * quantity) (should be negative)
        slProfit = (slPrice * entryQuantity) - (entryPrice * entryQuantity);
      }
    }
    
    // Use entry price from portfolio for basePrice if available
    const basePrice = entryPrice || avgPrice;
    
    // Use the first order's client_oid as baseOrderId (or generate one)
    const baseOrderId = clientOid.startsWith('standalone-') 
      ? sellOrders[0].order_id 
      : clientOid;
    
    // Find the earliest created_at
    const createdAts = sellOrders.map(o => o.created_at).filter(Boolean) as string[];
    const baseCreatedAt = createdAts.length > 0 
      ? new Date(Math.min(...createdAts.map(d => new Date(d).getTime()))).toISOString()
      : new Date().toISOString();
    
    // Transform child orders
    const childOrders = sellOrders.map(order => ({
      orderId: order.order_id,
      side: 'SELL' as const,
      type: (order.order_type === 'TAKE_PROFIT_LIMIT' || order.order_type === 'TAKE_PROFIT' || (order.is_trigger && order.trigger_type === 'TAKE_PROFIT'))
        ? 'TAKE_PROFIT' as const
        : (order.order_type === 'STOP_LOSS_LIMIT' || order.order_type === 'STOP_LOSS' || (order.is_trigger && order.trigger_type === 'STOP_LOSS'))
        ? 'STOP_LOSS' as const
        : 'SELL' as const,
      quantity: order.quantity || 0,
      price: order.price,
      createdAt: order.created_at || new Date().toISOString()
    }));
    
    const positionKey = `${symbol}_${baseOrderId}`;
    
    // Create or update position
    positionsMap.set(positionKey, {
      symbol,
      baseOrderId,
      baseSide: 'BUY' as const, // We assume there was a BUY order that created this position
      baseQuantity: entryQuantity,
      basePrice: basePrice,
      baseTotal: basePrice !== null && entryQuantity > 0 ? basePrice * entryQuantity : null,
      baseCreatedAt,
      netOpenQuantity: entryQuantity, // Use entry quantity from portfolio
      positionQuantity: entryQuantity,
      tpCount: tpOrders.length,
      slCount: slOrders.length,
      tpPrice,
      slPrice,
      tpProfit,
      slProfit,
      childOrders
    });
  });
  
  const result = Array.from(positionsMap.values());
  return result;
}



