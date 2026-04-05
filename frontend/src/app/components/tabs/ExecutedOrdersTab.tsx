/**
 * Executed Orders Tab Component
 * Extracted from page.tsx for better organization
 */

import React, { useState, useMemo, useEffect, useRef } from 'react';
import { OpenOrder } from '@/app/api';
import { formatDateTime, formatNumber } from '@/utils/formatting';
import { useOrders } from '@/hooks/useOrders';

type SortField = 'symbol' | 'side' | 'type' | 'quantity' | 'price' | 'status' | 'created_date' | 'execution_time' | 'total_value';
type SortDirection = 'asc' | 'desc';

const getStatusColorClass = (status: string) => {
  const lowerStatus = status.toLowerCase();
  if (lowerStatus === 'filled') return 'text-green-600 dark:text-green-400';
  if (lowerStatus === 'cancelled' || lowerStatus === 'rejected') return 'text-red-600 dark:text-red-400';
  return 'text-gray-600 dark:text-gray-400';
};

const getSideColorClass = (side: string) => {
  const lowerSide = side.toLowerCase();
  if (lowerSide === 'buy') return 'text-green-600 dark:text-green-400';
  if (lowerSide === 'sell') return 'text-red-600 dark:text-red-400';
  return 'text-gray-600 dark:text-gray-400';
};

interface ExecutedOrdersTabProps {
  orderFilter: { symbol: string; status: string; side: string; startDate: string; endDate: string };
  hideCancelled: boolean;
  onFilterChange: (filter: { symbol: string; status: string; side: string; startDate: string; endDate: string }) => void;
  onToggleHideCancelled: (value: boolean) => void;
  // Add other props as needed
}

export default function ExecutedOrdersTab({
  orderFilter,
  hideCancelled,
  onFilterChange,
  onToggleHideCancelled,
}: ExecutedOrdersTabProps) {
  const {
    executedOrders,
    executedOrdersLoading,
    executedOrdersError,
    executedOrdersLastUpdate,
    fetchExecutedOrders,
  } = useOrders();

  const [sortField, setSortField] = useState<SortField | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');

  // Fetch executed orders on mount (Strict Mode safe)
  const didFetchRef = useRef(false);
  useEffect(() => {
    if (didFetchRef.current) return;
    didFetchRef.current = true;

    fetchExecutedOrders({ showLoader: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Empty deps: only run on mount. fetchExecutedOrders is stable (useCallback with empty deps).

  // Filter orders
  const filteredOrders = useMemo(() => {
    if (!Array.isArray(executedOrders)) return [];
    
    const filtered = executedOrders.filter(order => {
      // Filter by symbol
      if (orderFilter.symbol && order.instrument_name) {
        if (!order.instrument_name.toLowerCase().includes(orderFilter.symbol.toLowerCase())) {
          return false;
        }
      }
      
      // Filter by status
      if (orderFilter.status && order.status !== orderFilter.status) {
        return false;
      }
      
      // Filter by side
      if (orderFilter.side && order.side !== orderFilter.side) {
        return false;
      }
      
      // Filter by date range
      if (orderFilter.startDate || orderFilter.endDate) {
        const orderDate = order.update_time 
          ? (typeof order.update_time === 'number' ? new Date(order.update_time) : new Date(order.update_time))
          : (order.create_time 
            ? (typeof order.create_time === 'number' ? new Date(order.create_time) : new Date(order.create_time))
            : null);
        
        if (orderDate && !isNaN(orderDate.getTime())) {
          const orderDateStr = orderDate.toISOString().split('T')[0];
          if (orderFilter.startDate && orderDateStr < orderFilter.startDate) {
            return false;
          }
          if (orderFilter.endDate && orderDateStr > orderFilter.endDate) {
            return false;
          }
        }
      }
      
      // Filter cancelled orders if hideCancelled is true
      if (hideCancelled && order.status) {
        const normalized = order.status.toUpperCase();
        if (normalized === 'CANCELLED' || normalized === 'CANCELED' || normalized === 'REJECTED' || normalized === 'EXPIRED') {
          return false;
        }
      }
      
      return true;
    });
    
    return filtered;
  }, [executedOrders, orderFilter, hideCancelled]);

  // Sort orders
  const sortedOrders = useMemo(() => {
    if (!sortField) {
      // Default: sort by execution time (newest first)
      return [...filteredOrders].sort((a, b) => {
        const aTime = a.update_time || a.create_time || 0;
        const bTime = b.update_time || b.create_time || 0;
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
          if (typeof aVal !== 'number') aVal = new Date(aVal as string).getTime();
          if (typeof bVal !== 'number') bVal = new Date(bVal as string).getTime();
          break;
        case 'execution_time':
          aVal = a.update_time || a.create_time || 0;
          bVal = b.update_time || b.create_time || 0;
          if (typeof aVal !== 'number') aVal = new Date(aVal as string).getTime();
          if (typeof bVal !== 'number') bVal = new Date(bVal as string).getTime();
          break;
        case 'total_value':
          aVal = parseFloat(a.quantity || '0') * parseFloat(a.price || '0');
          bVal = parseFloat(b.quantity || '0') * parseFloat(b.price || '0');
          break;
      }

      if (typeof aVal === 'string' && typeof bVal === 'string') {
        const aStr = aVal.toLowerCase();
        const bStr = bVal.toLowerCase();
        if (aStr < bStr) return sortDirection === 'asc' ? -1 : 1;
        if (aStr > bStr) return sortDirection === 'asc' ? 1 : -1;
        return 0;
      }

      if (typeof aVal === 'number' && typeof bVal === 'number') {
        if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1;
        if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1;
        return 0;
      }

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

  return (
    <div className="p-4 bg-white dark:bg-slate-900 rounded-lg shadow">
      <div className="flex flex-col md:flex-row md:justify-between md:items-center mb-4 gap-4">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Executed Orders - Crypto.com</h2>
        <div className="flex flex-wrap items-center gap-2 md:gap-4">
          {executedOrdersLastUpdate && (
            <div className="text-sm text-gray-500 dark:text-gray-400 whitespace-nowrap">
              <span className="mr-2">🕐</span>
              Last update: {formatDateTime(executedOrdersLastUpdate)}
            </div>
          )}
          <button
            onClick={() => fetchExecutedOrders({ showLoader: true })}
            disabled={executedOrdersLoading}
            className={`px-3 md:px-4 py-2 rounded-lg font-medium transition-all text-sm md:text-base whitespace-nowrap ${
              executedOrdersLoading
                ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                : 'bg-blue-600 text-white hover:bg-blue-700 active:bg-blue-800'
            }`}
          >
            {executedOrdersLoading ? '🔄 Updating...' : '↻ Refresh'}
          </button>
          <button
            onClick={() => onToggleHideCancelled(!hideCancelled)}
            className={`px-3 md:px-4 py-2 rounded-lg font-medium transition-all text-sm md:text-base whitespace-nowrap ${
              hideCancelled
                ? 'bg-blue-600 text-white hover:bg-blue-700 active:bg-blue-800'
                : 'bg-gray-200 text-gray-700 hover:bg-gray-300 active:bg-gray-400 dark:bg-slate-700 dark:text-gray-200 dark:hover:bg-slate-600'
            }`}
          >
            {hideCancelled ? '👁️ Show Cancelled' : '🙈 Hide Cancelled'}
          </button>
        </div>
      </div>

      {/* Filter Section */}
      <div className="mb-4 p-4 bg-gray-50 dark:bg-slate-800 rounded-lg">
        <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
          <input
            type="text"
            placeholder="Symbol"
            value={orderFilter.symbol}
            onChange={(e) => onFilterChange({ ...orderFilter, symbol: e.target.value })}
            className="px-3 py-2 border rounded dark:bg-slate-700 dark:border-slate-600 dark:text-white"
          />
          <select
            value={orderFilter.status}
            onChange={(e) => onFilterChange({ ...orderFilter, status: e.target.value })}
            className="px-3 py-2 border rounded dark:bg-slate-700 dark:border-slate-600 dark:text-white"
            aria-label="Filter by status"
          >
            <option value="">All Status</option>
            <option value="FILLED">Filled</option>
            <option value="CANCELLED">Cancelled</option>
            <option value="REJECTED">Rejected</option>
          </select>
          <select
            value={orderFilter.side}
            onChange={(e) => onFilterChange({ ...orderFilter, side: e.target.value })}
            className="px-3 py-2 border rounded dark:bg-slate-700 dark:border-slate-600 dark:text-white"
            aria-label="Filter by side"
          >
            <option value="">All Sides</option>
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
          <input
            type="date"
            value={orderFilter.startDate}
            onChange={(e) => onFilterChange({ ...orderFilter, startDate: e.target.value })}
            className="px-3 py-2 border rounded dark:bg-slate-700 dark:border-slate-600 dark:text-white"
            aria-label="Start date"
          />
          <input
            type="date"
            value={orderFilter.endDate}
            onChange={(e) => onFilterChange({ ...orderFilter, endDate: e.target.value })}
            className="px-3 py-2 border rounded dark:bg-slate-700 dark:border-slate-600 dark:text-white"
            aria-label="End date"
          />
        </div>
      </div>

      {executedOrdersError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm dark:bg-red-950 dark:border-red-700 dark:text-red-300">
          {executedOrdersError}
        </div>
      )}

      {executedOrdersLoading ? (
        <div className="text-center py-8 text-gray-500 dark:text-gray-400">Loading executed orders...</div>
      ) : sortedOrders.length === 0 ? (
        <div className="text-center py-8 text-gray-500 dark:text-gray-400">No executed orders</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-slate-800">
              <tr>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('created_date')}
                >
                  <div className="flex items-center gap-1">
                    Created Date {sortField === 'created_date' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('execution_time')}
                >
                  <div className="flex items-center gap-1">
                    Execution Time {sortField === 'execution_time' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('symbol')}
                >
                  <div className="flex items-center gap-1">
                    Symbol {sortField === 'symbol' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('side')}
                >
                  <div className="flex items-center gap-1">
                    Side {sortField === 'side' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('type')}
                >
                  <div className="flex items-center gap-1">
                    Type {sortField === 'type' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('quantity')}
                >
                  <div className="flex items-center gap-1">
                    Quantity {sortField === 'quantity' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('price')}
                >
                  <div className="flex items-center gap-1">
                    Price {sortField === 'price' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('total_value')}
                >
                  <div className="flex items-center gap-1">
                    Total Value {sortField === 'total_value' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('status')}
                >
                  <div className="flex items-center gap-1">
                    Status {sortField === 'status' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-slate-900 divide-y divide-gray-200 dark:divide-gray-700">
              {sortedOrders.map((order) => {
                const createTime = order.create_time 
                  ? (typeof order.create_time === 'number' ? new Date(order.create_time) : new Date(order.create_time))
                  : null;
                const updateTime = order.update_time 
                  ? (typeof order.update_time === 'number' ? new Date(order.update_time) : new Date(order.update_time))
                  : null;
                const createDatetime = createTime ? formatDateTime(createTime) : 'N/A';
                const updateDatetime = updateTime ? formatDateTime(updateTime) : createDatetime;
                
                return (
                  <tr key={order.order_id} className="hover:bg-gray-50 dark:hover:bg-slate-800">
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-gray-200">
                      {createDatetime}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-gray-200">
                      {updateDatetime}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-200">
                      {order.instrument_name}
                    </td>
                    <td className={`px-6 py-4 whitespace-nowrap text-sm font-medium ${getSideColorClass(order.side || '')}`}>
                      {order.side}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                      {order.order_type}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                      {formatNumber(parseFloat(order.quantity || '0'))}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                      {order.price ? formatNumber(parseFloat(order.price), order.instrument_name) : 'N/A'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                      {formatNumber(parseFloat(order.quantity || '0') * parseFloat(order.price || '0'), '$')}
                    </td>
                    <td className={`px-6 py-4 whitespace-nowrap text-sm font-semibold ${getStatusColorClass(order.status || '')}`}>
                      {order.status}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="mt-4 text-sm text-gray-600 dark:text-gray-400">
            Total orders: {sortedOrders.length}
          </div>
        </div>
      )}
    </div>
  );
}



