/**
 * Custom hook for orders state management
 * Extracted from page.tsx for better organization
 */

import { useState, useCallback, useEffect } from 'react';
import { 
  getDashboardState, 
  getDashboardSnapshot, 
  getOpenOrders,
  getOrderHistory,
  DashboardState, 
  OpenOrder 
} from '@/app/api';
import { logger } from '@/utils/logger';

export interface UseOrdersReturn {
  openOrders: OpenOrder[];
  openOrdersLoading: boolean;
  openOrdersError: string | null;
  openOrdersLastUpdate: Date | null;
  executedOrders: OpenOrder[];
  executedOrdersLoading: boolean;
  executedOrdersError: string | null;
  executedOrdersLastUpdate: Date | null;
  fetchOpenOrders: (options?: { showLoader?: boolean; backgroundRefresh?: boolean }) => Promise<void>;
  fetchExecutedOrders: (options?: { showLoader?: boolean }) => Promise<void>;
  setOpenOrders: (orders: OpenOrder[]) => void;
  setExecutedOrders: (orders: OpenOrder[]) => void;
}

export function useOrders(): UseOrdersReturn {
  const [openOrders, setOpenOrders] = useState<OpenOrder[]>([]);
  const [openOrdersLoading, setOpenOrdersLoading] = useState(true);
  const [openOrdersError, setOpenOrdersError] = useState<string | null>(null);
  const [openOrdersLastUpdate, setOpenOrdersLastUpdate] = useState<Date | null>(null);
  const [executedOrders, setExecutedOrders] = useState<OpenOrder[]>([]);
  const [executedOrdersLoading, setExecutedOrdersLoading] = useState(true);
  const [executedOrdersError, setExecutedOrdersError] = useState<string | null>(null);
  const [executedOrdersLastUpdate, setExecutedOrdersLastUpdate] = useState<Date | null>(null);

  const fetchOpenOrders = useCallback(async (options: { showLoader?: boolean; backgroundRefresh?: boolean } = {}) => {
    const { showLoader = false, backgroundRefresh = false } = options;
    if (showLoader) {
      setOpenOrdersLoading(true);
    }
    setOpenOrdersError(null);
    
    const updateOrdersFromState = (dashboardState: DashboardState, source: string): boolean => {
      if (dashboardState.open_orders && dashboardState.open_orders.length > 0) {
        const mappedOrders: OpenOrder[] = dashboardState.open_orders.map(order => {
          type ExtendedOrder = typeof order & {
            create_time?: number;
            create_datetime?: string;
            cumulative_value?: number | string;
            cumulative_quantity?: number | string;
            order_value?: number | string;
            avg_price?: number | string;
          };
          const extendedOrder = order as ExtendedOrder;
          
          const createTime = extendedOrder.create_time 
            ? extendedOrder.create_time 
            : (order.created_at ? new Date(order.created_at).getTime() : Date.now());
          
          const createDatetime = extendedOrder.create_datetime 
            ? extendedOrder.create_datetime 
            : (order.created_at || 'N/A');
          
          const updateTime = order.updated_at 
            ? new Date(order.updated_at).getTime() 
            : Date.now();
          
          return {
            order_id: order.exchange_order_id,
            instrument_name: order.symbol,
            side: order.side || 'UNKNOWN',
            order_type: order.order_type || 'LIMIT',
            quantity: order.quantity?.toString() || '0',
            price: order.price?.toString() || '0',
            status: order.status || 'UNKNOWN',
            create_time: createTime,
            create_datetime: createDatetime,
            created_at: order.created_at,
            update_time: updateTime,
            cumulative_value: extendedOrder.cumulative_value?.toString() || null,
            cumulative_quantity: extendedOrder.cumulative_quantity?.toString() || null,
            order_value: extendedOrder.order_value?.toString() || null,
            avg_price: extendedOrder.avg_price?.toString() || null
          };
        });
        
        logger.info(`📋 ${source} - Loaded ${mappedOrders.length} open orders`);
        setOpenOrders(mappedOrders);
        setOpenOrdersLastUpdate(new Date());
        setOpenOrdersError(null);
        return true;
      }
      return false;
    };
    
    try {
      logger.info('📸 Loading open orders from snapshot (fast)...');
      let snapshotLoaded = false;
      try {
        const snapshot = await getDashboardSnapshot();
        const dashboardState = snapshot.data;
        
        if (!snapshot.empty && dashboardState.open_orders && dashboardState.open_orders.length > 0) {
          logger.info(`✅ Snapshot loaded with ${dashboardState.open_orders.length} orders - displaying immediately`);
          snapshotLoaded = updateOrdersFromState(dashboardState, 'fetchOpenOrders:snapshot');
        }
      } catch (snapshotErr) {
        const errorMsg = snapshotErr instanceof Error ? snapshotErr.message : String(snapshotErr);
        if (!errorMsg.includes('Failed to fetch') && !errorMsg.includes('NetworkError')) {
          logger.logHandledError(
            'fetchOpenOrders:snapshot',
            'Failed to load snapshot - will try background refresh',
            snapshotErr,
            'warn'
          );
        } else {
          logger.debug('Open orders snapshot network error (expected occasionally):', errorMsg);
        }
      }
      
      if (!backgroundRefresh) {
        logger.info('🔄 Starting background refresh for open orders...');
        (async () => {
          try {
            const dashboardState = await getDashboardState();
            logger.info('✅ Background refresh completed - updating orders with fresh data');
            const ordersUpdated = updateOrdersFromState(dashboardState, 'fetchOpenOrders:background');
            
            // If dashboard state didn't have orders, try direct API call as fallback
            if (!ordersUpdated && !snapshotLoaded) {
              logger.info('⚠️ No orders found in dashboard state, trying direct API call...');
              try {
                const response = await getOpenOrders();
                logger.info(`✅ Direct API call returned ${response.orders?.length || 0} orders`);
                setOpenOrders(response.orders || []);
                setOpenOrdersLastUpdate(new Date());
                setOpenOrdersError(null);
              } catch (fallbackErr) {
                logger.logHandledError(
                  'fetchOpenOrders:fallback',
                  'Legacy open orders fallback also failed',
                  fallbackErr,
                  'warn'
                );
                setOpenOrdersError('Failed to refresh orders. Showing cached data if available.');
              }
            }
          } catch (refreshErr) {
            logger.logHandledError(
              'fetchOpenOrders:background',
              'Background refresh failed - trying direct API call',
              refreshErr,
              'warn'
            );
            // Always try direct API call if background refresh fails and snapshot didn't load
            if (!snapshotLoaded) {
              try {
                logger.info('🔄 Trying direct API call after background refresh failure...');
                const response = await getOpenOrders();
                logger.info(`✅ Direct API call returned ${response.orders?.length || 0} orders`);
                setOpenOrders(response.orders || []);
                setOpenOrdersLastUpdate(new Date());
                setOpenOrdersError(null);
              } catch (fallbackErr) {
                logger.logHandledError(
                  'fetchOpenOrders:fallback',
                  'Legacy open orders fallback also failed',
                  fallbackErr,
                  'warn'
                );
                setOpenOrdersError('Failed to refresh orders. Showing cached data if available.');
              }
            }
          }
        })();
      } else if (!snapshotLoaded) {
        // If background refresh is disabled and snapshot didn't load, try direct API call immediately
        logger.info('🔄 Snapshot didn\'t load, trying direct API call...');
        try {
          const response = await getOpenOrders();
          logger.info(`✅ Direct API call returned ${response.orders?.length || 0} orders`);
          setOpenOrders(response.orders || []);
          setOpenOrdersLastUpdate(new Date());
          setOpenOrdersError(null);
        } catch (fallbackErr) {
          logger.logHandledError(
            'fetchOpenOrders:direct',
            'Direct API call failed',
            fallbackErr,
            'warn'
          );
          setOpenOrdersError('Failed to load orders. Please try refreshing.');
        }
      }
    } catch (err) {
      logger.logHandledError(
        'fetchOpenOrders',
        'Failed to fetch open orders - keeping last known data visible',
        err,
        'warn'
      );
      setOpenOrdersError('Failed to load orders. Retrying in background...');
    } finally {
      setOpenOrdersLoading(false);
    }
  }, []);

  const fetchExecutedOrders = useCallback(async (options: { showLoader?: boolean } = {}) => {
    const { showLoader = false } = options;
    if (showLoader) {
      setExecutedOrdersLoading(true);
    }
    setExecutedOrdersError(null);
    
    try {
      logger.info('🔄 Fetching executed orders...');
      const response = await getOrderHistory(100, 0, true); // sync=true to fetch latest from exchange
      const orders = response.orders || [];
      
      setExecutedOrders(orders);
      setExecutedOrdersLastUpdate(new Date());
      setExecutedOrdersError(null);
      logger.info(`✅ Loaded ${orders.length} executed orders`);
    } catch (err) {
      logger.error('❌ Error in fetchExecutedOrders:', err);
      logger.logHandledError(
        'fetchExecutedOrders',
        'Failed to fetch executed orders (request will retry on next tick)',
        err,
        'warn'
      );
      setExecutedOrdersError('Failed to load executed orders. Retrying...');
    } finally {
      setExecutedOrdersLoading(false);
    }
  }, []);

  // Fetch orders on mount
  useEffect(() => {
    logger.info('🔄 useOrders: Fetching open orders on mount');
    fetchOpenOrders({ showLoader: true });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    openOrders,
    openOrdersLoading,
    openOrdersError,
    openOrdersLastUpdate,
    executedOrders,
    executedOrdersLoading,
    executedOrdersError,
    executedOrdersLastUpdate,
    fetchOpenOrders,
    fetchExecutedOrders,
    setOpenOrders,
    setExecutedOrders,
  };
}



