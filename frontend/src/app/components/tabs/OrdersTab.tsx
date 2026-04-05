/**
 * Orders Tab Component
 * Extracted from page.tsx for better organization
 */

import React, { useState, useMemo, useCallback } from 'react';
import { OpenOrder, quickOrder } from '@/app/api';
import { formatDateTime, formatNumber } from '@/utils/formatting';
import { useOrders } from '@/hooks/useOrders';
import { logger } from '@/utils/logger';

type SortField = 'symbol' | 'side' | 'type' | 'quantity' | 'price' | 'status' | 'created_date';
type SortDirection = 'asc' | 'desc';

const isCancelledStatus = (status: string | undefined): boolean => {
  if (!status) return false;
  const upperStatus = status.toUpperCase();
  return upperStatus === 'CANCELLED' || upperStatus === 'CANCELED' || upperStatus === 'REJECTED' || upperStatus === 'EXPIRED';
};

interface OrdersTabProps {
  botStatus: { is_running: boolean; status: 'running' | 'stopped'; reason: string | null; live_trading_enabled?: boolean; mode?: 'LIVE' | 'DRY_RUN' } | null;
  togglingLiveTrading: boolean;
  isUpdating: boolean;
  topCoinsLoading: boolean;
  portfolioLoading: boolean;
  hideCancelledOpenOrders: boolean;
  onToggleLiveTrading: () => Promise<void>;
  onToggleHideCancelled: (value: boolean) => void;
  // Add other props as needed
}

export default function OrdersTab({
  botStatus,
  togglingLiveTrading,
  isUpdating,
  topCoinsLoading,
  portfolioLoading,
  hideCancelledOpenOrders,
  onToggleLiveTrading,
  onToggleHideCancelled,
}: OrdersTabProps) {
  const {
    openOrders,
    openOrdersLoading,
    openOrdersError,
    openOrdersLastUpdate,
    fetchOpenOrders,
  } = useOrders();

  const [sortField, setSortField] = useState<SortField | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [cancellingOrderId, setCancellingOrderId] = useState<string | null>(null);

  // Note: fetchOpenOrders is already called on mount by the useOrders hook (line 280 in useOrders.ts)
  // No need to call it again here to avoid duplicate API requests

  // Filter orders
  const filteredOrders = useMemo(() => {
    if (!Array.isArray(openOrders)) return [];
    
    let filtered = [...openOrders];
    
    // Filter out cancelled orders if hideCancelledOpenOrders is true
    if (hideCancelledOpenOrders) {
      filtered = filtered.filter(order => !isCancelledStatus(order.status));
    }
    
    return filtered;
  }, [openOrders, hideCancelledOpenOrders]);

  // Sort orders
  const sortedOrders = useMemo(() => {
    if (!sortField) {
      // Default: sort by creation date (newest first)
      return [...filteredOrders].sort((a, b) => {
        const aTime = a.create_time || 0;
        const bTime = b.create_time || 0;
        const aNum = typeof aTime === 'number' ? aTime : (typeof aTime === 'string' ? new Date(aTime).getTime() : 0);
        const bNum = typeof bTime === 'number' ? bTime : (typeof bTime === 'string' ? new Date(bTime).getTime() : 0);
        return bNum - aNum;
      });
    }

    return [...filteredOrders].sort((a, b) => {
      let aVal: unknown = 0;
      let bVal: unknown = 0;

      switch (sortField) {
        case 'symbol':
          aVal = a.instrument_name || '';
          bVal = b.instrument_name || '';
          break;
        case 'side':
          aVal = a.side || '';
          bVal = b.side || '';
          break;
        case 'type':
          aVal = a.order_type || '';
          bVal = b.order_type || '';
          break;
        case 'quantity':
          aVal = parseFloat(a.quantity || '0');
          bVal = parseFloat(b.quantity || '0');
          break;
        case 'price':
          aVal = parseFloat(a.price || '0');
          bVal = parseFloat(b.price || '0');
          break;
        case 'status':
          aVal = a.status || '';
          bVal = b.status || '';
          break;
        case 'created_date':
          aVal = a.create_time || 0;
          bVal = b.create_time || 0;
          if (typeof aVal !== 'number') aVal = new Date(aVal).getTime();
          if (typeof bVal !== 'number') bVal = new Date(bVal).getTime();
          break;
      }

      if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1;
      return 0;
    });
  }, [filteredOrders, sortField, sortDirection]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  const handleCancelOrder = useCallback(async (orderId: string) => {
    if (!confirm('Are you sure you want to cancel this order?')) {
      return;
    }

    setCancellingOrderId(orderId);
    try {
      await quickOrder({
        action: 'cancel',
        order_id: orderId,
      });
      logger.info(`✅ Order ${orderId} cancelled successfully`);
      
      // Refresh orders after cancellation
      await fetchOpenOrders({ showLoader: false, backgroundRefresh: true });
    } catch (error) {
      logger.error(`❌ Failed to cancel order ${orderId}:`, error);
      alert(`Failed to cancel order: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setCancellingOrderId(null);
    }
  }, [fetchOpenOrders]);

  const getStatusColor = (status: string | undefined) => {
    if (!status) return 'text-gray-500';
    const upperStatus = status.toUpperCase();
    if (upperStatus === 'FILLED' || upperStatus === 'ACTIVE' || upperStatus === 'NEW') {
      return 'text-green-600';
    }
    if (isCancelledStatus(status)) {
      return 'text-red-600';
    }
    return 'text-yellow-600';
  };

  const getSideColor = (side: string | undefined) => {
    if (!side) return 'text-gray-500';
    const upperSide = side.toUpperCase();
    return upperSide === 'BUY' ? 'text-green-600 font-semibold' : 'text-red-600 font-semibold';
  };

  return (
    <div>
      <div className="flex flex-col md:flex-row md:justify-between md:items-center mb-4 gap-4">
        <h2 className="text-xl font-semibold">Open Orders - Crypto.com</h2>
        <div className="flex flex-wrap items-center gap-2 md:gap-4">
          {openOrdersLastUpdate && (
            <div className="text-sm text-gray-500 whitespace-nowrap">
              <span className="mr-2">🕐</span>
              Last update: {formatDateTime(openOrdersLastUpdate)}
            </div>
          )}
          {botStatus && (
            <>
              <div className={`px-3 py-1 rounded-full text-xs font-semibold whitespace-nowrap ${
                botStatus.is_running 
                  ? 'bg-green-100 text-green-700' 
                  : 'bg-red-100 text-red-700'
              }`} title={botStatus.reason || undefined}>
                {botStatus.is_running ? '🟢 Bot Activo' : '🔴 Bot Detenido'}
              </div>
              <button
                onClick={onToggleLiveTrading}
                disabled={togglingLiveTrading || isUpdating || topCoinsLoading || portfolioLoading}
                className={`px-3 py-1 rounded-full text-xs font-semibold transition-colors whitespace-nowrap ${
                  botStatus.live_trading_enabled
                    ? 'bg-green-600 text-white hover:bg-green-700'
                    : 'bg-gray-400 text-white hover:bg-gray-500'
                }`}
              >
                {togglingLiveTrading ? '⏳' : botStatus.live_trading_enabled ? '🟢 LIVE' : '🔴 DRY RUN'}
              </button>
            </>
          )}
          <button
            onClick={() => fetchOpenOrders({ showLoader: true })}
            disabled={openOrdersLoading}
            className={`px-3 md:px-4 py-2 rounded-lg font-medium transition-all text-sm md:text-base whitespace-nowrap ${
              openOrdersLoading
                ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                : 'bg-blue-600 text-white hover:bg-blue-700 active:bg-blue-800'
            }`}
          >
            {openOrdersLoading ? '🔄 Updating...' : '↻ Refresh'}
          </button>
          <button
            onClick={() => onToggleHideCancelled(!hideCancelledOpenOrders)}
            className={`px-3 md:px-4 py-2 rounded-lg font-medium transition-all text-sm md:text-base whitespace-nowrap ${
              hideCancelledOpenOrders
                ? 'bg-blue-600 text-white hover:bg-blue-700'
                : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
            }`}
          >
            {hideCancelledOpenOrders ? '👁️ Show Cancelled' : '🙈 Hide Cancelled'}
          </button>
        </div>
      </div>

      {openOrdersError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
          {openOrdersError}
        </div>
      )}

      {openOrdersLoading ? (
        <div className="text-center py-8 text-gray-500">Loading orders...</div>
      ) : sortedOrders.length === 0 ? (
        <div className="text-center py-8 text-gray-500">No open orders</div>
      ) : (
        <div className="bg-white dark:bg-slate-800 rounded-lg shadow overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
              <thead className="bg-gray-50 dark:bg-slate-700">
                <tr>
                  <th
                    className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-600"
                    onClick={() => handleSort('created_date')}
                  >
                    Date {sortField === 'created_date' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </th>
                  <th
                    className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-600"
                    onClick={() => handleSort('symbol')}
                  >
                    Symbol {sortField === 'symbol' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </th>
                  <th
                    className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-600"
                    onClick={() => handleSort('side')}
                  >
                    Side {sortField === 'side' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </th>
                  <th
                    className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-600"
                    onClick={() => handleSort('type')}
                  >
                    Type {sortField === 'type' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </th>
                  <th
                    className="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-600"
                    onClick={() => handleSort('quantity')}
                  >
                    Quantity {sortField === 'quantity' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </th>
                  <th
                    className="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-600"
                    onClick={() => handleSort('price')}
                  >
                    Price {sortField === 'price' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                    Total Value
                  </th>
                  <th
                    className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-600"
                    onClick={() => handleSort('status')}
                  >
                    Status {sortField === 'status' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white dark:bg-slate-800 divide-y divide-gray-200 dark:divide-gray-700">
                {sortedOrders.map((order) => {
                  const quantity = parseFloat(order.quantity || '0');
                  const price = parseFloat(order.price || '0');
                  const totalValue = quantity * price;
                  const createTime = order.create_time 
                    ? (typeof order.create_time === 'number' ? new Date(order.create_time) : new Date(order.create_time))
                    : null;
                  const canCancel = order.status && 
                    !isCancelledStatus(order.status) && 
                    order.status.toUpperCase() !== 'FILLED' &&
                    botStatus?.live_trading_enabled;

                  return (
                    <tr key={order.order_id} className="hover:bg-gray-50 dark:hover:bg-slate-700">
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900 dark:text-gray-100">
                        {createTime ? formatDateTime(createTime) : 'N/A'}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white">
                        {order.instrument_name || 'N/A'}
                      </td>
                      <td className={`px-4 py-3 whitespace-nowrap text-sm ${getSideColor(order.side)}`}>
                        {order.side || 'N/A'}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900 dark:text-gray-100">
                        {order.order_type || 'LIMIT'}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-right text-gray-900 dark:text-gray-100">
                        {formatNumber(quantity)}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-right text-gray-900 dark:text-gray-100">
                        {price > 0 ? formatNumber(price) : 'Market'}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-right text-gray-900 dark:text-gray-100">
                        {totalValue > 0 ? `$${formatNumber(totalValue)}` : '-'}
                      </td>
                      <td className={`px-4 py-3 whitespace-nowrap text-sm font-medium ${getStatusColor(order.status)}`}>
                        {order.status || 'UNKNOWN'}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-center text-sm">
                        {canCancel && (
                          <button
                            onClick={() => handleCancelOrder(order.order_id)}
                            disabled={cancellingOrderId === order.order_id}
                            className="px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-xs"
                          >
                            {cancellingOrderId === order.order_id ? 'Cancelling...' : 'Cancel'}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="px-4 py-3 bg-gray-50 dark:bg-slate-700 text-sm text-gray-500 dark:text-gray-400">
            Total: {sortedOrders.length} order{sortedOrders.length !== 1 ? 's' : ''}
          </div>
        </div>
      )}
    </div>
  );
}



