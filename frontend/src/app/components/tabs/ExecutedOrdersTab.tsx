/**
 * Executed Orders Tab Component
 * Extracted from page.tsx for better organization
 */

import React, { useState, useMemo, useEffect, useRef } from 'react';
import { OpenOrder, TopCoin } from '@/app/api';
import { formatDateTime, formatNumber } from '@/utils/formatting';
import { sideBadgeClass, sideLabelEs } from '@/utils/tradeSideLabels';
import { useOrders } from '@/hooks/useOrders';
import {
  buildOpenLotsByOrderId,
  buildRealizedPnlByOrderId,
  getExecutedOrderDisplayPnl,
  getPnlUnavailableTooltip,
  isClosedExecutedEntryOrder,
  isFilledEntryOrder,
  resolveCurrentPrice,
} from '@/utils/orderProfitLoss';

type SortField =
  | 'symbol'
  | 'side'
  | 'type'
  | 'quantity'
  | 'price'
  | 'status'
  | 'created_date'
  | 'execution_time'
  | 'total_value'
  | 'pnl'
  | 'pnl_percent';
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

const getExecutionOriginBadgeClass = (origin?: string, typeDisplay?: string) => {
  const label = (typeDisplay || origin || '').toLowerCase();
  if (label.includes('sl ejecutado') || origin === 'STOP_LOSS') {
    return 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200';
  }
  if (label.includes('tp ejecutado') || origin === 'TAKE_PROFIT') {
    return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200';
  }
  if (label.includes('alerta') || origin === 'ALERT') {
    return 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200';
  }
  if (label.includes('manual') || origin === 'MANUAL') {
    return 'bg-gray-100 text-gray-700 dark:bg-slate-700 dark:text-gray-200';
  }
  return 'text-gray-500 dark:text-gray-400';
};

const getOrderTypeLabel = (order: OpenOrder) =>
  order.type_display || order.execution_origin_label || order.order_type;

interface ExecutedOrdersTabProps {
  orderFilter: { symbol: string; status: string; side: string; startDate: string; endDate: string };
  hideCancelled: boolean;
  onFilterChange: (filter: { symbol: string; status: string; side: string; startDate: string; endDate: string }) => void;
  onToggleHideCancelled: (value: boolean) => void;
  onNavigateToExpectedTP?: (symbol: string, orderId: string) => void;
  /** Mark prices for unrealized P/L (same source as Portfolio / Watchlist). */
  topCoins?: TopCoin[];
}

export default function ExecutedOrdersTab({
  orderFilter,
  hideCancelled,
  onFilterChange,
  onToggleHideCancelled,
  onNavigateToExpectedTP,
  topCoins = [],
}: ExecutedOrdersTabProps) {
  const {
    executedOrders,
    executedOrdersLoading,
    executedOrdersLoadingMore,
    executedOrdersError,
    executedOrdersLastUpdate,
    executedOrdersHasMore,
    executedOrdersTotal,
    fetchExecutedOrders,
  } = useOrders();

  const [sortField, setSortField] = useState<SortField | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');

  // FIFO open lots only — do not trim by portfolio balance (Portfolio tab owns that).
  const openLotsByOrderId = useMemo(
    () => buildOpenLotsByOrderId(executedOrders),
    [executedOrders]
  );

  const realizedByOrderId = useMemo(
    () => buildRealizedPnlByOrderId(executedOrders),
    [executedOrders]
  );

  // Fetch on mount and whenever Hide Cancelled toggles (server-side exclude_cancelled).
  // Strict Mode safe: skip duplicate mount with same excludeCancelled value.
  const lastExcludeRef = useRef<boolean | null>(null);
  useEffect(() => {
    if (lastExcludeRef.current === hideCancelled) return;
    lastExcludeRef.current = hideCancelled;
    fetchExecutedOrders({ showLoader: true, excludeCancelled: hideCancelled });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hideCancelled]);

  const statusSummary = useMemo(() => {
    if (!Array.isArray(executedOrders)) {
      return { cancelledLike: 0 };
    }
    let cancelledLike = 0;
    for (const order of executedOrders) {
      const normalized = (order.status || '').toUpperCase();
      if (
        normalized === 'CANCELLED' ||
        normalized === 'CANCELED' ||
        normalized === 'REJECTED' ||
        normalized === 'EXPIRED'
      ) {
        cancelledLike += 1;
      }
    }
    return { cancelledLike };
  }, [executedOrders]);

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
          aVal = getOrderTypeLabel(a);
          bVal = getOrderTypeLabel(b);
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
        case 'pnl':
        case 'pnl_percent': {
          const aPrice = resolveCurrentPrice(a.instrument_name, topCoins);
          const bPrice = resolveCurrentPrice(b.instrument_name, topCoins);
          const aPnl = getExecutedOrderDisplayPnl(
            a,
            executedOrders,
            aPrice,
            openLotsByOrderId,
            realizedByOrderId
          );
          const bPnl = getExecutedOrderDisplayPnl(
            b,
            executedOrders,
            bPrice,
            openLotsByOrderId,
            realizedByOrderId
          );
          aVal = aPnl.available ? (sortField === 'pnl' ? aPnl.pnl : aPnl.pnlPercent) : Number.NEGATIVE_INFINITY;
          bVal = bPnl.available ? (sortField === 'pnl' ? bPnl.pnl : bPnl.pnlPercent) : Number.NEGATIVE_INFINITY;
          break;
        }
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
  }, [
    filteredOrders,
    sortField,
    sortDirection,
    topCoins,
    executedOrders,
    openLotsByOrderId,
    realizedByOrderId,
  ]);

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
            onClick={() =>
              fetchExecutedOrders({
                showLoader: true,
                sync: true,
                excludeCancelled: hideCancelled,
              })
            }
            disabled={executedOrdersLoading || executedOrdersLoadingMore}
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

      {!executedOrdersLoading && (
        <div className="mb-3 text-sm text-gray-600 dark:text-gray-400">
          Mostrando {sortedOrders.length}
          {executedOrdersTotal != null ? ` de ${executedOrdersTotal}` : ''}
          {hideCancelled
            ? ' (canceladas/rechazadas ocultas)'
            : statusSummary.cancelledLike > 0
              ? ` · ${statusSummary.cancelledLike} canceladas/rechazadas en esta página`
              : ''}
          {executedOrdersHasMore ? ' · hay más páginas' : ''}
        </div>
      )}

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
        <div className="text-center py-8 text-gray-500 dark:text-gray-400">
          <p>No executed orders</p>
          {executedOrdersHasMore && (
            <button
              type="button"
              onClick={() =>
                fetchExecutedOrders({
                  loadMore: true,
                  excludeCancelled: hideCancelled,
                })
              }
              disabled={executedOrdersLoadingMore}
              className="mt-4 px-4 py-2 rounded-lg font-medium text-sm bg-slate-800 text-white hover:bg-slate-700 disabled:bg-gray-300 disabled:text-gray-500"
            >
              {executedOrdersLoadingMore ? 'Cargando…' : 'Cargar más'}
            </button>
          )}
        </div>
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
                    Dirección {sortField === 'side' && (sortDirection === 'asc' ? '↑' : '↓')}
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
                  onClick={() => handleSort('pnl_percent')}
                  title="Ganancia/pérdida % vs precio actual (abiertas) o vs contraparte (cerradas)"
                >
                  <div className="flex items-center gap-1">
                    P&amp;L % {sortField === 'pnl_percent' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('pnl')}
                  title="Beneficio neto en USD: long gana si sube el precio; short gana si baja"
                >
                  <div className="flex items-center gap-1">
                    Beneficio neto {sortField === 'pnl' && (sortDirection === 'asc' ? '↑' : '↓')}
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
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
                >
                  TP/SL
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
                const markPrice = resolveCurrentPrice(order.instrument_name, topCoins);
                const pnlData = getExecutedOrderDisplayPnl(
                  order,
                  executedOrders,
                  markPrice,
                  openLotsByOrderId,
                  realizedByOrderId
                );
                const hasPnl = pnlData.available;
                const pnlPositive = pnlData.pnl >= 0;
                const pnlColorClass = pnlPositive
                  ? 'text-green-600 dark:text-green-400'
                  : 'text-red-600 dark:text-red-400';
                const isClosedEntry = isClosedExecutedEntryOrder(
                  order,
                  openLotsByOrderId,
                  realizedByOrderId
                );
                // Bold + "orden cerrada" only with numeric FIFO realized P/L.
                const realizationLabel = isClosedEntry
                  ? 'orden cerrada'
                  : pnlData.isRealized
                    ? 'realizado'
                    : 'no realizado';
                const realizationTitle = isClosedEntry
                  ? 'P&L realizado (orden cerrada vs contraparte FIFO)'
                  : pnlData.isRealized
                    ? 'P&L realizado vs orden contraparte'
                    : hasPnl
                      ? 'P&L no realizado vs precio actual (long gana si sube; short si baja)'
                      : getPnlUnavailableTooltip(pnlData.unavailableReason);
                
                return (
                  <tr
                    key={order.order_id}
                    className={`hover:bg-gray-50 dark:hover:bg-slate-800${isClosedEntry ? ' font-bold' : ''}`}
                  >
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-gray-200">
                      {createDatetime}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-gray-200">
                      {updateDatetime}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-200">
                      {order.instrument_name}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <div className="flex flex-col gap-1">
                        <span className={`inline-flex w-fit px-2 py-1 rounded text-xs font-semibold ${sideBadgeClass(order.side)}`}>
                          {sideLabelEs(order.side)}
                        </span>
                        <span className={`text-xs font-medium ${getSideColorClass(order.side || '')}`}>
                          {order.side}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <div className="flex flex-col gap-1">
                        <span
                          className={`inline-flex w-fit px-2 py-1 rounded text-xs font-semibold ${getExecutionOriginBadgeClass(order.execution_origin, getOrderTypeLabel(order))}`}
                          title={order.execution_origin ? `Origen: ${order.execution_origin}` : undefined}
                        >
                          {getOrderTypeLabel(order)}
                        </span>
                        {getOrderTypeLabel(order) !== order.order_type && (
                          <span className="text-xs text-gray-400 dark:text-gray-500">{order.order_type}</span>
                        )}
                      </div>
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
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      {hasPnl ? (
                        <span className={`font-medium ${pnlColorClass}`} title={realizationTitle}>
                          {pnlPositive ? '+' : ''}
                          {pnlData.pnlPercent.toFixed(2)}%
                          <span className={`ml-1 text-gray-400 ${isClosedEntry ? '' : 'font-normal'}`}>
                            ({realizationLabel})
                          </span>
                        </span>
                      ) : (
                        <span
                          className="text-gray-400 dark:text-gray-500"
                          title={realizationTitle}
                        >
                          —
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      {hasPnl ? (
                        <span className={`font-medium ${pnlColorClass}`} title={realizationTitle}>
                          {pnlPositive ? '+' : '-'}
                          {formatNumber(Math.abs(pnlData.pnl), '$')}
                        </span>
                      ) : (
                        <span
                          className="text-gray-400 dark:text-gray-500"
                          title={realizationTitle}
                        >
                          —
                        </span>
                      )}
                    </td>
                    <td className={`px-6 py-4 whitespace-nowrap text-sm font-semibold ${getStatusColorClass(order.status || '')}`}>
                      {order.status}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      {isFilledEntryOrder(order) ? (
                        <div className="flex flex-wrap items-center gap-2">
                          {order.is_orphan && (
                            <span
                              className="px-2 py-1 rounded text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200"
                              title="Sin TP ni SL vinculados"
                            >
                              Huérfano
                            </span>
                          )}
                          {onNavigateToExpectedTP && order.instrument_name && order.order_id && (
                            <button
                              type="button"
                              onClick={() => onNavigateToExpectedTP(order.instrument_name!, order.order_id!)}
                              className="text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300"
                            >
                              Ver TP/SL
                            </button>
                          )}
                        </div>
                      ) : (
                        <span className="text-gray-400 dark:text-gray-500">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="mt-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div className="text-sm text-gray-600 dark:text-gray-400">
              Mostrando {sortedOrders.length}
              {executedOrdersTotal != null ? ` de ${executedOrdersTotal}` : ''} órdenes
              {hideCancelled ? ' (sin canceladas)' : ''}
            </div>
            {executedOrdersHasMore && (
              <button
                type="button"
                onClick={() =>
                  fetchExecutedOrders({
                    loadMore: true,
                    excludeCancelled: hideCancelled,
                  })
                }
                disabled={executedOrdersLoadingMore || executedOrdersLoading}
                className={`px-4 py-2 rounded-lg font-medium text-sm whitespace-nowrap ${
                  executedOrdersLoadingMore || executedOrdersLoading
                    ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                    : 'bg-slate-800 text-white hover:bg-slate-700 dark:bg-slate-600 dark:hover:bg-slate-500'
                }`}
              >
                {executedOrdersLoadingMore ? 'Cargando…' : 'Cargar más'}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}



