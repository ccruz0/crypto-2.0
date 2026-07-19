/**
 * Expected Take Profit Tab Component
 * Extracted from page.tsx for better organization
 */

import React, { useState, useMemo, useEffect, useRef } from 'react';
import { ExpectedTPSummaryItem, ExpectedTPDetails, ExpectedTPEntryOrder } from '@/app/api';
import { formatDateTime, formatNumber } from '@/utils/formatting';
import {
  positionBadgeClass,
  positionDirectionEs,
  sideBadgeClass,
  sideLabelEs,
} from '@/utils/tradeSideLabels';
import {
  formatTpFillProximityPct,
  tpFillProximityPct,
  tpFillProximityToneClass,
} from '@/utils/tpFillProximity';

type SortField =
  | 'symbol'
  | 'net_qty'
  | 'position_value'
  | 'avg_entry_price'
  | 'covered_qty'
  | 'uncovered_qty'
  | 'total_expected_profit'
  | 'current_price'
  | 'coverage_ratio'
  | 'max_tp_fill_proximity_pct';
type SortDirection = 'asc' | 'desc';

const TP_PROXIMITY_TOOLTIP =
  'Cercanía al fill del TP: progreso del precio desde la entrada hacia el TP. 100% = mark en o más allá del precio del TP (cerca de ejecutarse). No es cobertura de cantidad.';

interface ExpectedTakeProfitTabProps {
  expectedTPSummary: ExpectedTPSummaryItem[];
  expectedTPLoading: boolean;
  expectedTPLastUpdate: Date | null;
  expectedTPDetails: ExpectedTPDetails | null;
  expectedTPDetailsLoading: boolean;
  expectedTPDetailsSymbol: string | null;
  showExpectedTPDetailsDialog: boolean;
  deepLink?: { symbol: string; orderId: string } | null;
  onFetchExpectedTakeProfitSummary: () => Promise<void>;
  onFetchExpectedTakeProfitDetails: (symbol: string) => Promise<void>;
  onCloseDetailsDialog: () => void;
  onDeepLinkHandled?: () => void;
}

export default function ExpectedTakeProfitTab({
  expectedTPSummary,
  expectedTPLoading,
  expectedTPLastUpdate,
  expectedTPDetails,
  expectedTPDetailsLoading,
  expectedTPDetailsSymbol,
  showExpectedTPDetailsDialog,
  deepLink,
  onFetchExpectedTakeProfitSummary,
  onFetchExpectedTakeProfitDetails,
  onCloseDetailsDialog,
  onDeepLinkHandled,
}: ExpectedTakeProfitTabProps) {
  const [sortField, setSortField] = useState<SortField | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [expandedEntryRows, setExpandedEntryRows] = useState<Set<string>>(new Set());
  const [highlightOrderId, setHighlightOrderId] = useState<string | null>(null);
  const deepLinkRequestedRef = useRef(false);

  const toggleEntryRow = (rowKey: string) => {
    setExpandedEntryRows((prev) => {
      const next = new Set(prev);
      if (next.has(rowKey)) {
        next.delete(rowKey);
      } else {
        next.add(rowKey);
      }
      return next;
    });
  };

  const entryOrders = useMemo(() => {
    if (!expectedTPDetails?.entry_orders?.length) return [];
    return expectedTPDetails.entry_orders;
  }, [expectedTPDetails]);

  // When details open, expand every entry that has TP/SL so nested rows are visible
  // without a second click (summary chevron → details should feel like one expand).
  useEffect(() => {
    if (!showExpectedTPDetailsDialog || expectedTPDetailsLoading || !expectedTPDetails) {
      return;
    }
    // Deep-link already sets a specific expansion; don't override it.
    if (deepLink?.orderId) {
      return;
    }
    const keys = (expectedTPDetails.entry_orders || [])
      .map((entry, index) => {
        const rowKey = entry.order_id || `entry-${index}`;
        const hasChildren = entry.take_profits.length > 0 || entry.stop_loss !== null;
        return hasChildren ? rowKey : null;
      })
      .filter((k): k is string => Boolean(k));
    setExpandedEntryRows(new Set(keys));
  }, [
    showExpectedTPDetailsDialog,
    expectedTPDetailsLoading,
    expectedTPDetails,
    deepLink?.orderId,
  ]);

  useEffect(() => {
    if (!showExpectedTPDetailsDialog) {
      setExpandedEntryRows(new Set());
    }
  }, [showExpectedTPDetailsDialog]);

  const formatSignedUsd = (value: number | null | undefined, forceSign: 'positive' | 'negative') => {
    if (value === null || value === undefined) return '—';
    const displayValue = forceSign === 'positive' ? Math.abs(value) : -Math.abs(value);
    const prefix = displayValue >= 0 ? '+' : '';
    return `${prefix}${formatNumber(displayValue, '$')}`;
  };

  const formatSignedPct = (value: number | null | undefined, forceSign: 'positive' | 'negative') => {
    if (value === null || value === undefined) return '—';
    const displayValue = forceSign === 'positive' ? Math.abs(value) : -Math.abs(value);
    const prefix = displayValue >= 0 ? '+' : '';
    return `${prefix}${displayValue.toFixed(2)}%`;
  };

  const sideLabel = (side: ExpectedTPEntryOrder['side']) => sideLabelEs(side);

  const positionLabel = (positionSide?: string | null) => positionDirectionEs(positionSide);

  const statusBadgeClass = (status: string) => {
    if (status === 'FILLED' || status === 'ACTIVE') {
      return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200';
    }
    if (status === 'CANCELLED' || status === 'REJECTED') {
      return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200';
    }
    return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200';
  };

  // Fetch expected take profit summary on mount (Strict Mode safe)
  const didFetchRef = useRef(false);
  useEffect(() => {
    if (didFetchRef.current) return;
    didFetchRef.current = true;

    onFetchExpectedTakeProfitSummary();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Empty deps: only run on mount. onFetchExpectedTakeProfitSummary is passed as prop from parent.

  useEffect(() => {
    if (!deepLink) {
      deepLinkRequestedRef.current = false;
      return;
    }
    if (deepLinkRequestedRef.current) return;
    deepLinkRequestedRef.current = true;
    onFetchExpectedTakeProfitDetails(deepLink.symbol);
  }, [deepLink, onFetchExpectedTakeProfitDetails]);

  useEffect(() => {
    if (!deepLink?.orderId || expectedTPDetailsLoading || !expectedTPDetails || !showExpectedTPDetailsDialog) {
      return;
    }

    const targetId = deepLink.orderId;
    setHighlightOrderId(targetId);
    setExpandedEntryRows(new Set([targetId]));

    const scrollTimer = window.setTimeout(() => {
      document.getElementById(`expected-tp-entry-${targetId}`)?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
    }, 150);

    const clearTimer = window.setTimeout(() => {
      setHighlightOrderId(null);
      onDeepLinkHandled?.();
    }, 5000);

    return () => {
      window.clearTimeout(scrollTimer);
      window.clearTimeout(clearTimer);
    };
  }, [deepLink, expectedTPDetails, expectedTPDetailsLoading, showExpectedTPDetailsDialog, onDeepLinkHandled]);

  // Sort summary items
  const sortedSummary = useMemo(() => {
    if (!expectedTPSummary || expectedTPSummary.length === 0) return [];
    if (!sortField) {
      // Default: sort by total_expected_profit (highest first)
      return [...expectedTPSummary].sort((a, b) => (b.total_expected_profit || 0) - (a.total_expected_profit || 0));
    }

    return [...expectedTPSummary].sort((a, b) => {
      let aVal: unknown = 0;
      let bVal: unknown = 0;

      switch (sortField) {
        case 'symbol':
          aVal = (a.symbol || '').toLowerCase();
          bVal = (b.symbol || '').toLowerCase();
          break;
        case 'net_qty':
          aVal = a.net_qty || 0;
          bVal = b.net_qty || 0;
          break;
        case 'position_value':
          aVal = a.position_value || 0;
          bVal = b.position_value || 0;
          break;
        case 'avg_entry_price':
          aVal = a.avg_entry_price ?? 0;
          bVal = b.avg_entry_price ?? 0;
          break;
        case 'covered_qty':
          aVal = a.covered_qty || 0;
          bVal = b.covered_qty || 0;
          break;
        case 'uncovered_qty':
          aVal = a.uncovered_qty || 0;
          bVal = b.uncovered_qty || 0;
          break;
        case 'total_expected_profit':
          aVal = a.total_expected_profit || 0;
          bVal = b.total_expected_profit || 0;
          break;
        case 'current_price':
          aVal = a.current_price || 0;
          bVal = b.current_price || 0;
          break;
        case 'coverage_ratio':
          aVal = a.coverage_ratio || 0;
          bVal = b.coverage_ratio || 0;
          break;
        case 'max_tp_fill_proximity_pct':
          aVal = a.max_tp_fill_proximity_pct ?? -1;
          bVal = b.max_tp_fill_proximity_pct ?? -1;
          break;
      }

      if (typeof aVal === 'string' && typeof bVal === 'string') {
        if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1;
        if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1;
        return 0;
      }

      if (typeof aVal === 'number' && typeof bVal === 'number') {
        if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1;
        if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1;
        return 0;
      }

      return 0;
    });
  }, [expectedTPSummary, sortField, sortDirection]);

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
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Expected Take Profit</h2>
        <div className="flex flex-wrap items-center gap-2 md:gap-4">
          {expectedTPLastUpdate && (
            <div className="text-sm text-gray-500 dark:text-gray-400 whitespace-nowrap">
              <span className="mr-2">🕐</span>
              Last update: {formatDateTime(expectedTPLastUpdate)}
            </div>
          )}
          <button
            onClick={onFetchExpectedTakeProfitSummary}
            disabled={expectedTPLoading}
            className={`px-3 md:px-4 py-2 rounded-lg font-medium transition-all text-sm md:text-base whitespace-nowrap ${
              expectedTPLoading
                ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                : 'bg-blue-600 text-white hover:bg-blue-700 active:bg-blue-800'
            }`}
          >
            {expectedTPLoading ? '🔄 Updating...' : '↻ Refresh'}
          </button>
        </div>
      </div>

      {expectedTPLoading ? (
        <div className="text-center py-8 text-gray-500 dark:text-gray-400">Loading expected take profit data...</div>
      ) : sortedSummary.length === 0 ? (
        <div className="text-center py-8 text-gray-500 dark:text-gray-400">No expected take profit data available</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-slate-800">
              <tr>
                <th
                  scope="col"
                  className="sticky left-0 z-10 bg-gray-50 dark:bg-slate-800 px-2 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider w-10"
                >
                  <span className="sr-only">Expandir</span>
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
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
                >
                  Dirección
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('net_qty')}
                  title="Suma de cantidades de lotes abiertos (no inventario neto firmado)"
                >
                  <div className="flex items-center gap-1">
                    Net Qty {sortField === 'net_qty' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('position_value')}
                >
                  <div className="flex items-center gap-1">
                    Position Value {sortField === 'position_value' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('avg_entry_price')}
                  title="Precio de entrada promedio (ponderado por cantidad). Ver Detalles para cada orden."
                >
                  <div className="flex items-center gap-1">
                    Entry / Avg {sortField === 'avg_entry_price' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('covered_qty')}
                >
                  <div className="flex items-center gap-1">
                    Covered Qty {sortField === 'covered_qty' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('uncovered_qty')}
                >
                  <div className="flex items-center gap-1">
                    Uncovered Qty {sortField === 'uncovered_qty' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('total_expected_profit')}
                >
                  <div className="flex items-center gap-1">
                    Expected Profit {sortField === 'total_expected_profit' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('current_price')}
                >
                  <div className="flex items-center gap-1">
                    Current Price {sortField === 'current_price' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('coverage_ratio')}
                >
                  <div className="flex items-center gap-1">
                    Coverage Ratio {sortField === 'coverage_ratio' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  onClick={() => handleSort('max_tp_fill_proximity_pct')}
                  title={TP_PROXIMITY_TOOLTIP}
                >
                  <div className="flex items-center gap-1">
                    TP cerca %{' '}
                    {sortField === 'max_tp_fill_proximity_pct' && (sortDirection === 'asc' ? '↑' : '↓')}
                  </div>
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
                >
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-slate-900 divide-y divide-gray-200 dark:divide-gray-700">
              {sortedSummary.map((item) => {
                const isDetailsOpen =
                  showExpectedTPDetailsDialog && expectedTPDetailsSymbol === item.symbol;
                const isDetailsLoading =
                  expectedTPDetailsLoading && expectedTPDetailsSymbol === item.symbol;
                return (
                <tr
                  key={item.symbol}
                  className="hover:bg-gray-50 dark:hover:bg-slate-800 cursor-pointer"
                  onClick={() => onFetchExpectedTakeProfitDetails(item.symbol)}
                >
                  <td className="sticky left-0 z-10 bg-white dark:bg-slate-900 px-2 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    <button
                      type="button"
                      className="inline-flex w-6 h-6 items-center justify-center rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-600"
                      aria-expanded={isDetailsOpen}
                      aria-label={
                        isDetailsLoading
                          ? `Cargando detalles de ${item.symbol}`
                          : isDetailsOpen
                            ? `Cerrar detalles de ${item.symbol}`
                            : `Expandir detalles de ${item.symbol}`
                      }
                      title={isDetailsLoading ? 'Cargando…' : isDetailsOpen ? 'Cerrar' : 'Ver TP/SL'}
                      onClick={(e) => {
                        e.stopPropagation();
                        if (isDetailsOpen) {
                          onCloseDetailsDialog();
                        } else {
                          onFetchExpectedTakeProfitDetails(item.symbol);
                        }
                      }}
                    >
                      {isDetailsLoading ? '…' : isDetailsOpen ? '▾' : '▸'}
                    </button>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-200">
                    {item.symbol}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm">
                    <span
                      className={`px-2 py-1 rounded text-xs font-semibold ${positionBadgeClass(item.position_side)}`}
                      title={positionDirectionEs(item.position_side)}
                    >
                      {positionLabel(item.position_side)}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {formatNumber(item.net_qty)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {formatNumber(item.position_value, '$')}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {item.cost_basis_unknown || item.avg_entry_price == null ? (
                      <span className="text-gray-400 dark:text-gray-500" title="Cost basis not tracked">
                        —
                      </span>
                    ) : (
                      <div>
                        <div className="text-gray-900 dark:text-gray-200">
                          {formatNumber(item.avg_entry_price, item.symbol)}
                        </div>
                        {(item.entry_lot_count ?? 0) > 1 && (
                          <div className="text-xs text-gray-500 dark:text-gray-400">
                            avg · {item.entry_lot_count} lots
                          </div>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {formatNumber(item.covered_qty)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {formatNumber(item.uncovered_qty)}
                  </td>
                  {item.cost_basis_unknown ? (
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-semibold text-gray-400 dark:text-gray-500" title="Cost basis not tracked (no recorded buy orders)">
                      —
                    </td>
                  ) : (
                    <td className={`px-6 py-4 whitespace-nowrap text-sm font-semibold ${
                      (item.total_expected_profit || 0) >= 0 
                        ? 'text-green-600 dark:text-green-400' 
                        : 'text-red-600 dark:text-red-400'
                    }`}>
                      {formatNumber(item.total_expected_profit, '$')}
                    </td>
                  )}
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {item.current_price ? formatNumber(item.current_price, item.symbol) : 'N/A'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {item.coverage_ratio !== undefined && item.coverage_ratio !== null 
                      ? `${(item.coverage_ratio * 100).toFixed(1)}%` 
                      : 'N/A'}
                  </td>
                  <td
                    className={`px-6 py-4 whitespace-nowrap text-sm ${tpFillProximityToneClass(item.max_tp_fill_proximity_pct)}`}
                    title={TP_PROXIMITY_TOOLTIP}
                  >
                    {formatTpFillProximityPct(item.max_tp_fill_proximity_pct)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onFetchExpectedTakeProfitDetails(item.symbol);
                      }}
                      className="text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300"
                    >
                      View Details
                    </button>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
          <div className="mt-4 text-sm text-gray-600 dark:text-gray-400">
            Total symbols: {sortedSummary.length}
          </div>
        </div>
      )}

      {/* Details Dialog */}
      {showExpectedTPDetailsDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={onCloseDetailsDialog}>
          <div className="bg-white dark:bg-slate-800 rounded-lg p-6 max-w-5xl w-full max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-start mb-4 gap-4">
              <div>
                <h3 className="text-xl font-semibold text-gray-900 dark:text-white">
                  Expected TP Details: {expectedTPDetailsSymbol}
                </h3>
                {expectedTPDetails?.position_side && (
                  <div className="mt-2">
                    <span
                      className={`px-2 py-1 rounded text-sm font-semibold ${positionBadgeClass(expectedTPDetails.position_side)}`}
                    >
                      {positionLabel(expectedTPDetails.position_side)}
                    </span>
                  </div>
                )}
              </div>
              <button
                onClick={onCloseDetailsDialog}
                className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 text-2xl leading-none"
              >
                ✕
              </button>
            </div>
            {expectedTPDetailsLoading ? (
              <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                <p className="mt-2">Loading details...</p>
              </div>
            ) : expectedTPDetails ? (
              <div className="space-y-6">
                {expectedTPDetails.orphaned_protection_only && (
                  <div className="rounded-lg border border-orange-300 bg-orange-50 dark:border-orange-700 dark:bg-orange-900/30 p-3 text-sm text-orange-800 dark:text-orange-200">
                    Portfolio balance is zero or negative, but active SL/TP protection orders
                    remain on the exchange. Entry orders below show orphaned protection linked
                    to prior filled buys — not an open spot position.
                  </div>
                )}
                {expectedTPDetails.cost_basis_unknown && (
                  <div className="rounded-lg border border-amber-300 bg-amber-50 dark:border-amber-700 dark:bg-amber-900/30 p-3 text-sm text-amber-800 dark:text-amber-200">
                    Cost basis not tracked for this position — there are no recorded buy orders,
                    so the buy price and expected profit cannot be computed and are shown as "—".
                    Quantities and current position value remain accurate.
                  </div>
                )}
                {/* Summary Section */}
                <div className="bg-gray-50 dark:bg-slate-700 rounded-lg p-4">
                  <h4 className="text-lg font-semibold mb-3 text-gray-900 dark:text-white">Summary</h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div>
                      <div
                        className="text-sm text-gray-600 dark:text-gray-400"
                        title="Suma de cantidades de lotes abiertos (cada entrada con SL/TP activo). No es el inventario neto firmado Long−Short."
                      >
                        Open Lots Qty
                      </div>
                      <div className="text-lg font-semibold text-gray-900 dark:text-white">
                        {formatNumber(expectedTPDetails.net_qty)}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-gray-600 dark:text-gray-400">Position Value</div>
                      <div className="text-lg font-semibold text-gray-900 dark:text-white">
                        {formatNumber(expectedTPDetails.position_value, '$')}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-gray-600 dark:text-gray-400">Covered Qty</div>
                      <div className="text-lg font-semibold text-green-600 dark:text-green-400">
                        {formatNumber(expectedTPDetails.covered_qty)}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-gray-600 dark:text-gray-400">Uncovered Qty</div>
                      <div className="text-lg font-semibold text-orange-600 dark:text-orange-400">
                        {formatNumber(expectedTPDetails.uncovered_qty)}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-gray-600 dark:text-gray-400">Expected Profit</div>
                      {expectedTPDetails.cost_basis_unknown ? (
                        <div className="text-lg font-semibold text-gray-400 dark:text-gray-500" title="Cost basis not tracked (no recorded buy orders)">
                          —
                        </div>
                      ) : (
                        <div className={`text-lg font-semibold ${
                          (expectedTPDetails.total_expected_profit || 0) >= 0
                            ? 'text-green-600 dark:text-green-400'
                            : 'text-red-600 dark:text-red-400'
                        }`}>
                          {formatNumber(expectedTPDetails.total_expected_profit, '$')}
                        </div>
                      )}
                    </div>
                    {expectedTPDetails.current_price !== undefined && (
                      <div>
                        <div className="text-sm text-gray-600 dark:text-gray-400">Current Price</div>
                        <div className="text-lg font-semibold text-gray-900 dark:text-white">
                          {formatNumber(expectedTPDetails.current_price, expectedTPDetailsSymbol || '')}
                        </div>
                      </div>
                    )}
                    <div>
                      <div className="text-sm text-gray-600 dark:text-gray-400">
                        {(expectedTPDetails.entry_lot_count ?? 0) > 1 ? 'Avg Entry' : 'Entry Price'}
                      </div>
                      {expectedTPDetails.cost_basis_unknown || expectedTPDetails.avg_entry_price == null ? (
                        <div className="text-lg font-semibold text-gray-400 dark:text-gray-500" title="Cost basis not tracked">
                          —
                        </div>
                      ) : (
                        <div className="text-lg font-semibold text-gray-900 dark:text-white">
                          {formatNumber(expectedTPDetails.avg_entry_price, expectedTPDetailsSymbol || '')}
                          {(expectedTPDetails.entry_lot_count ?? 0) > 1 && (
                            <span className="ml-2 text-xs font-normal text-gray-500 dark:text-gray-400">
                              ({expectedTPDetails.entry_lot_count} lots)
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                    {expectedTPDetails.uncovered_entry && (
                      <div className="col-span-2">
                        <div className="text-sm text-gray-600 dark:text-gray-400">Uncovered Entry</div>
                        <div className="text-lg font-semibold text-orange-600 dark:text-orange-400">
                          {formatNumber(expectedTPDetails.uncovered_entry.uncovered_qty)} - {expectedTPDetails.uncovered_entry.label}
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Entry Orders Section (expandable TP / SL per original order) */}
                {entryOrders.length > 0 ? (
                  <div>
                    <h4 className="text-lg font-semibold mb-1 text-gray-900 dark:text-white">
                      Entry Orders ({entryOrders.length})
                    </h4>
                    <p className="mb-3 text-sm text-gray-600 dark:text-gray-400">
                      Inventario por lote: cada fila es una entrada ejecutada que aún espera su SL/TP.
                      {expectedTPDetails.position_side === 'MIXED' && (
                        <> Incluye lotes Long (Compra) y Short (Venta) a la vez.</>
                      )}
                    </p>
                    <div className="overflow-x-auto">
                      <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                        <thead className="bg-gray-50 dark:bg-slate-700">
                          <tr>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider w-10">
                              <span className="sr-only">Expand</span>
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                              Par
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                              Order ID
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                              Dirección
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                              Entry Price
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                              Qty
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                              Entry Time
                            </th>
                          </tr>
                        </thead>
                        <tbody className="bg-white dark:bg-slate-800 divide-y divide-gray-200 dark:divide-gray-700">
                          {entryOrders.map((entry, index) => {
                            const rowKey = entry.order_id || `entry-${index}`;
                            const isExpanded = expandedEntryRows.has(rowKey);
                            const hasChildren = entry.take_profits.length > 0 || entry.stop_loss !== null;

                            return (
                              <React.Fragment key={rowKey}>
                                <tr
                                  id={`expected-tp-entry-${rowKey}`}
                                  className={`hover:bg-gray-50 dark:hover:bg-slate-700 ${
                                    highlightOrderId === rowKey || highlightOrderId === entry.order_id
                                      ? 'ring-2 ring-blue-500 ring-inset bg-blue-50/50 dark:bg-blue-950/30'
                                      : ''
                                  }`}
                                >
                                  <td className="px-4 py-3 whitespace-nowrap text-sm">
                                    {hasChildren ? (
                                      <button
                                        type="button"
                                        onClick={() => toggleEntryRow(rowKey)}
                                        className="w-6 h-6 inline-flex items-center justify-center rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-600"
                                        aria-expanded={isExpanded}
                                        title={isExpanded ? 'Contraer TP/SL' : 'Expandir TP/SL'}
                                      >
                                        {isExpanded ? '▾' : '▸'}
                                      </button>
                                    ) : (
                                      <span className="inline-block w-6 text-center text-gray-400">·</span>
                                    )}
                                  </td>
                                  <td className="px-4 py-3 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-200">
                                    {entry.symbol || expectedTPDetailsSymbol || '—'}
                                  </td>
                                  <td className="px-4 py-3 whitespace-nowrap text-sm font-mono text-xs text-gray-900 dark:text-gray-200">
                                    {entry.order_id || '—'}
                                  </td>
                                  <td className="px-4 py-3 whitespace-nowrap text-sm">
                                    <span className={`px-2 py-1 rounded text-xs font-semibold ${sideBadgeClass(entry.side)}`}>
                                      {sideLabel(entry.side)}
                                    </span>
                                  </td>
                                  <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900 dark:text-gray-200">
                                    {entry.cost_basis_unknown ? (
                                      <span className="text-gray-400 dark:text-gray-500" title="Cost basis not tracked">
                                        —
                                      </span>
                                    ) : (
                                      formatNumber(entry.entry_price, expectedTPDetailsSymbol || entry.side)
                                    )}
                                  </td>
                                  <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900 dark:text-gray-200">
                                    {formatNumber(entry.qty)}
                                  </td>
                                  <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                                    {entry.entry_time ? formatDateTime(new Date(entry.entry_time)) : 'N/A'}
                                  </td>
                                </tr>

                                {isExpanded && hasChildren && (
                                  <>
                                    {entry.take_profits.map((tp) => {
                                      const proximity =
                                        tp.tp_fill_proximity_pct ??
                                        tpFillProximityPct({
                                          mark: expectedTPDetails.current_price,
                                          entry: entry.entry_price,
                                          tp: tp.price,
                                        });
                                      const proximityLabel = formatTpFillProximityPct(proximity);
                                      const proximityTitle =
                                        proximity == null
                                          ? TP_PROXIMITY_TOOLTIP
                                          : `Cercanía TP: ${proximityLabel}. ${TP_PROXIMITY_TOOLTIP}`;

                                      return (
                                      <tr
                                        key={`${rowKey}-tp-${tp.order_id}`}
                                        className="bg-green-50/60 dark:bg-green-950/20"
                                        title={proximityTitle}
                                      >
                                        <td className="px-4 py-2" />
                                        <td className="px-4 py-2 whitespace-nowrap text-sm font-mono text-xs pl-8 text-gray-700 dark:text-gray-300" colSpan={3}>
                                          <span className="font-semibold text-green-700 dark:text-green-400 mr-2">TP</span>
                                          {tp.side && (
                                            <span className={`px-2 py-0.5 rounded text-xs font-semibold mr-2 ${sideBadgeClass(tp.side)}`}>
                                              {sideLabel(tp.side)}
                                            </span>
                                          )}
                                          {tp.order_id}
                                        </td>
                                        <td className="px-4 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-gray-200">
                                          {tp.price !== null ? formatNumber(tp.price, expectedTPDetailsSymbol || '') : '—'}
                                        </td>
                                        <td className="px-4 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-gray-200">
                                          {formatNumber(tp.qty)}
                                        </td>
                                        <td className="px-4 py-2 whitespace-nowrap text-sm">
                                          <div className="flex flex-wrap items-center gap-2">
                                            <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusBadgeClass(tp.status)}`}>
                                              {tp.status}
                                            </span>
                                            <span className="font-semibold text-green-600 dark:text-green-400">
                                              {formatSignedUsd(tp.expected_amount_usd, 'positive')}
                                            </span>
                                            <span className="text-xs text-green-700 dark:text-green-300">
                                              ({formatSignedPct(tp.expected_amount_pct, 'positive')})
                                            </span>
                                            {proximity != null && (
                                              <span
                                                className={`text-xs ${tpFillProximityToneClass(proximity)}`}
                                                title={proximityTitle}
                                              >
                                                Cercanía TP: {proximityLabel}
                                              </span>
                                            )}
                                          </div>
                                        </td>
                                      </tr>
                                      );
                                    })}

                                    {entry.stop_loss && (
                                      <tr key={`${rowKey}-sl-${entry.stop_loss.order_id}`} className="bg-red-50/60 dark:bg-red-950/20">
                                        <td className="px-4 py-2" />
                                        <td className="px-4 py-2 whitespace-nowrap text-sm font-mono text-xs pl-8 text-gray-700 dark:text-gray-300" colSpan={3}>
                                          <span className="font-semibold text-red-700 dark:text-red-400 mr-2">SL</span>
                                          {entry.stop_loss.order_id}
                                        </td>
                                        <td className="px-4 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-gray-200">
                                          {entry.stop_loss.price !== null
                                            ? formatNumber(entry.stop_loss.price, expectedTPDetailsSymbol || '')
                                            : '—'}
                                        </td>
                                        <td className="px-4 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-gray-200">
                                          {formatNumber(entry.stop_loss.qty)}
                                        </td>
                                        <td className="px-4 py-2 whitespace-nowrap text-sm">
                                          <div className="flex flex-wrap items-center gap-2">
                                            <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusBadgeClass(entry.stop_loss.status)}`}>
                                              {entry.stop_loss.status}
                                            </span>
                                            <span className="font-semibold text-red-600 dark:text-red-400">
                                              {formatSignedUsd(entry.stop_loss.expected_amount_usd, 'negative')}
                                            </span>
                                            <span className="text-xs text-red-700 dark:text-red-300">
                                              ({formatSignedPct(entry.stop_loss.expected_amount_pct, 'negative')})
                                            </span>
                                          </div>
                                        </td>
                                      </tr>
                                    )}
                                  </>
                                )}
                              </React.Fragment>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : expectedTPDetails.matched_lots && expectedTPDetails.matched_lots.length > 0 ? (
                  <div>
                    <h4 className="text-lg font-semibold mb-3 text-gray-900 dark:text-white">
                      Matched Lots ({expectedTPDetails.matched_lots.length})
                    </h4>
                    <div className="overflow-x-auto">
                      <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                        <thead className="bg-gray-50 dark:bg-slate-700">
                          <tr>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                              Buy Order
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                              Buy Price
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                              Buy Time
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                              Qty
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                              TP Order
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                              TP Price
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                              TP Qty
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                              TP Status
                            </th>
                            <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                              Expected Profit
                            </th>
                          </tr>
                        </thead>
                        <tbody className="bg-white dark:bg-slate-800 divide-y divide-gray-200 dark:divide-gray-700">
                          {expectedTPDetails.matched_lots.map((lot, index) => (
                            <tr key={index} className="hover:bg-gray-50 dark:hover:bg-slate-700">
                              <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900 dark:text-gray-200">
                                {lot.is_grouped && lot.buy_order_ids ? (
                                  <div>
                                    <div className="font-medium">{lot.buy_order_count || lot.buy_order_ids.length} orders</div>
                                    <div className="text-xs text-gray-500 dark:text-gray-400">{lot.buy_order_id}...</div>
                                  </div>
                                ) : (
                                  <div className="font-mono text-xs">{lot.buy_order_id}</div>
                                )}
                              </td>
                              <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900 dark:text-gray-200">
                                {lot.cost_basis_unknown ? (
                                  <span className="text-gray-400 dark:text-gray-500" title="Cost basis not tracked (no recorded buy orders)">
                                    Cost basis not tracked
                                  </span>
                                ) : (
                                  formatNumber(lot.buy_price, lot.symbol)
                                )}
                              </td>
                              <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                                {lot.buy_time ? formatDateTime(new Date(lot.buy_time)) : 'N/A'}
                              </td>
                              <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900 dark:text-gray-200">
                                {formatNumber(lot.lot_qty)}
                              </td>
                              <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900 dark:text-gray-200">
                                <div className="font-mono text-xs">{lot.tp_order_id}</div>
                              </td>
                              <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900 dark:text-gray-200">
                                {formatNumber(lot.tp_price, lot.symbol)}
                              </td>
                              <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900 dark:text-gray-200">
                                {formatNumber(lot.tp_qty)}
                              </td>
                              <td className="px-4 py-3 whitespace-nowrap text-sm">
                                <span className={`px-2 py-1 rounded text-xs font-medium ${
                                  lot.tp_status === 'FILLED' || lot.tp_status === 'ACTIVE'
                                    ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
                                    : lot.tp_status === 'CANCELLED' || lot.tp_status === 'REJECTED'
                                    ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
                                    : 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200'
                                }`}>
                                  {lot.tp_status}
                                </span>
                              </td>
                              <td className="px-4 py-3 whitespace-nowrap text-sm text-right">
                                {lot.cost_basis_unknown ? (
                                  <div className="font-semibold text-gray-400 dark:text-gray-500" title="Cost basis not tracked (no recorded buy orders)">
                                    —
                                  </div>
                                ) : (
                                  <>
                                    <div className={`font-semibold ${
                                      (lot.expected_profit || 0) >= 0
                                        ? 'text-green-600 dark:text-green-400'
                                        : 'text-red-600 dark:text-red-400'
                                    }`}>
                                      {formatNumber(lot.expected_profit, '$')}
                                    </div>
                                    {lot.expected_profit_pct !== undefined && lot.expected_profit_pct !== null && (
                                      <div className="text-xs text-gray-500 dark:text-gray-400">
                                        ({lot.expected_profit_pct >= 0 ? '+' : ''}{lot.expected_profit_pct.toFixed(2)}%)
                                      </div>
                                    )}
                                  </>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : (expectedTPDetails.covered_qty ?? 0) > 0 || expectedTPDetails.orphaned_protection_only ? (
                  <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                    Active protection orders are listed under Entry Orders above.
                  </div>
                ) : (
                  <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                    No matched lots found
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center py-8 text-red-500 dark:text-red-400">
                Failed to load details. Please try again.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}



