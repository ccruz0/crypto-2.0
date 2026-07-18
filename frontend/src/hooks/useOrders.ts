/**
 * Custom hook for orders state management
 * Extracted from page.tsx for better organization
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import { 
  getDashboardState, 
  getDashboardSnapshot, 
  getOpenOrders,
  getOrderHistory,
  DashboardState, 
  OpenOrder,
  OpenOrdersSyncMeta,
} from '@/app/api';
import { logger } from '@/utils/logger';

const EXECUTED_ORDERS_PAGE_SIZE = 100;

export type FetchExecutedOrdersOptions = {
  showLoader?: boolean;
  sync?: boolean;
  /** @deprecated Prefer sync; kept for slow-tick callers */
  loadAll?: boolean;
  /** Append next page (uses current list length as offset) */
  loadMore?: boolean;
  /** When true, request exclude_cancelled so FILLED rows are not lost to client filtering */
  excludeCancelled?: boolean;
};

export interface UseOrdersReturn {
  openOrders: OpenOrder[];
  openOrdersLoading: boolean;
  openOrdersError: string | null;
  openOrdersLastUpdate: Date | null;
  openOrdersSyncStatus: OpenOrdersSyncMeta['sync_status'] | null;
  openOrdersDataVerified: boolean | null;
  openOrdersSyncError: string | null;
  executedOrders: OpenOrder[];
  executedOrdersLoading: boolean;
  executedOrdersLoadingMore: boolean;
  executedOrdersError: string | null;
  executedOrdersLastUpdate: Date | null;
  executedOrdersHasMore: boolean;
  executedOrdersTotal: number | null;
  fetchOpenOrders: (options?: { showLoader?: boolean; backgroundRefresh?: boolean }) => Promise<void>;
  fetchExecutedOrders: (options?: FetchExecutedOrdersOptions) => Promise<void>;
  setOpenOrders: (orders: OpenOrder[]) => void;
  setExecutedOrders: (orders: OpenOrder[]) => void;
}

export function useOrders(): UseOrdersReturn {
  const [openOrders, setOpenOrders] = useState<OpenOrder[]>([]);
  const [openOrdersLoading, setOpenOrdersLoading] = useState(true);
  const [openOrdersError, setOpenOrdersError] = useState<string | null>(null);
  const [openOrdersLastUpdate, setOpenOrdersLastUpdate] = useState<Date | null>(null);
  const [openOrdersSyncStatus, setOpenOrdersSyncStatus] = useState<OpenOrdersSyncMeta['sync_status'] | null>(null);
  const [openOrdersDataVerified, setOpenOrdersDataVerified] = useState<boolean | null>(null);
  const [openOrdersSyncError, setOpenOrdersSyncError] = useState<string | null>(null);
  const [executedOrders, setExecutedOrders] = useState<OpenOrder[]>([]);
  const [executedOrdersLoading, setExecutedOrdersLoading] = useState(true);
  const [executedOrdersLoadingMore, setExecutedOrdersLoadingMore] = useState(false);
  const [executedOrdersError, setExecutedOrdersError] = useState<string | null>(null);
  const [executedOrdersLastUpdate, setExecutedOrdersLastUpdate] = useState<Date | null>(null);
  const [executedOrdersHasMore, setExecutedOrdersHasMore] = useState(false);
  const [executedOrdersTotal, setExecutedOrdersTotal] = useState<number | null>(null);
  const executedOrdersRef = useRef<OpenOrder[]>([]);
  const excludeCancelledRef = useRef<boolean>(true);

  useEffect(() => {
    executedOrdersRef.current = executedOrders;
  }, [executedOrders]);

  const fetchOpenOrders = useCallback(async (options: { showLoader?: boolean; backgroundRefresh?: boolean } = {}) => {
    const { showLoader = false, backgroundRefresh = false } = options;
    if (showLoader) {
      setOpenOrdersLoading(true);
    }
    setOpenOrdersError(null);

    const applySyncMeta = (payload: Partial<OpenOrdersSyncMeta>) => {
      if (payload.sync_status !== undefined) setOpenOrdersSyncStatus(payload.sync_status ?? null);
      if (payload.data_verified !== undefined) setOpenOrdersDataVerified(payload.data_verified ?? null);
      if (payload.data_verified === false) {
        setOpenOrdersSyncError(
          payload.error_message ||
            'Open orders could not be verified. Crypto.com authentication failed. Showing cached or unavailable data.'
        );
      } else if (payload.data_verified === true) {
        setOpenOrdersSyncError(null);
      }
    };

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
        applySyncMeta({
          sync_status: dashboardState.open_orders_sync_status,
          data_verified: dashboardState.open_orders_data_verified,
        });
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
                applySyncMeta(response);
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
                applySyncMeta(response);
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

  const fetchExecutedOrders = useCallback(async (options: FetchExecutedOrdersOptions = {}) => {
    const {
      showLoader = false,
      sync = false,
      loadAll = false,
      loadMore = false,
      excludeCancelled = excludeCancelledRef.current,
    } = options;
    const doSync = (sync || loadAll) && !loadMore;
    excludeCancelledRef.current = excludeCancelled;

    if (loadMore) {
      setExecutedOrdersLoadingMore(true);
    } else if (showLoader) {
      setExecutedOrdersLoading(true);
    }
    setExecutedOrdersError(null);

    // Safety: ensure loading never hangs forever (API timeout is 60s; we give 65s then force-clear)
    const SAFETY_MS = 65_000;
    const safetyTimer = setTimeout(() => {
      setExecutedOrdersLoading(false);
      setExecutedOrdersLoadingMore(false);
      setExecutedOrdersError('Request took too long. Click Refresh to try again.');
    }, SAFETY_MS);

    try {
      const offset = loadMore ? executedOrdersRef.current.length : 0;
      logger.info('🔄 Fetching executed orders...', {
        sync: doSync,
        loadMore,
        offset,
        excludeCancelled,
      });
      const response = await getOrderHistory({
        limit: EXECUTED_ORDERS_PAGE_SIZE,
        offset,
        sync: doSync,
        excludeCancelled,
      });
      const orders = response.orders || [];

      if (loadMore) {
        const existingIds = new Set(
          executedOrdersRef.current.map((o) => o.order_id).filter(Boolean)
        );
        const merged = [
          ...executedOrdersRef.current,
          ...orders.filter((o) => o.order_id && !existingIds.has(o.order_id)),
        ];
        setExecutedOrders(merged);
        executedOrdersRef.current = merged;
      } else {
        setExecutedOrders(orders);
        executedOrdersRef.current = orders;
      }

      setExecutedOrdersHasMore(Boolean(response.has_more));
      setExecutedOrdersTotal(
        typeof response.total === 'number' ? response.total : null
      );
      setExecutedOrdersLastUpdate(new Date());
      setExecutedOrdersError(null);
      logger.info(
        `✅ Loaded ${orders.length} executed orders (page offset=${offset}, has_more=${response.has_more})`
      );
    } catch (err) {
      logger.error('❌ Error in fetchExecutedOrders:', err);
      logger.logHandledError(
        'fetchExecutedOrders',
        'Failed to fetch executed orders (request will retry on next tick)',
        err,
        'warn'
      );
      setExecutedOrdersError('Failed to load executed orders. Click Refresh to try again.');
    } finally {
      clearTimeout(safetyTimer);
      setExecutedOrdersLoading(false);
      setExecutedOrdersLoadingMore(false);
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
    openOrdersSyncStatus,
    openOrdersDataVerified,
    openOrdersSyncError,
    executedOrders,
    executedOrdersLoading,
    executedOrdersLoadingMore,
    executedOrdersError,
    executedOrdersLastUpdate,
    executedOrdersHasMore,
    executedOrdersTotal,
    fetchOpenOrders,
    fetchExecutedOrders,
    setOpenOrders,
    setExecutedOrders,
  };
}
