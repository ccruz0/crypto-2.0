/**
 * Expected Take Profit Tab Component
 * Extracted from page.tsx for better organization
 */

import React, { useState, useMemo, useEffect, useRef } from 'react';
import { ExpectedTPSummaryItem, ExpectedTPDetails } from '@/app/api';
import { formatDateTime, formatNumber } from '@/utils/formatting';

type SortField = 'symbol' | 'net_qty' | 'position_value' | 'covered_qty' | 'uncovered_qty' | 'total_expected_profit' | 'current_price' | 'coverage_ratio';
type SortDirection = 'asc' | 'desc';

interface ExpectedTakeProfitTabProps {
  expectedTPSummary: ExpectedTPSummaryItem[];
  expectedTPLoading: boolean;
  expectedTPLastUpdate: Date | null;
  expectedTPDetails: ExpectedTPDetails | null;
  expectedTPDetailsLoading: boolean;
  expectedTPDetailsSymbol: string | null;
  showExpectedTPDetailsDialog: boolean;
  onFetchExpectedTakeProfitSummary: () => Promise<void>;
  onFetchExpectedTakeProfitDetails: (symbol: string) => Promise<void>;
  onCloseDetailsDialog: () => void;
  // Add other props as needed
}

export default function ExpectedTakeProfitTab({
  expectedTPSummary,
  expectedTPLoading,
  expectedTPLastUpdate,
  expectedTPDetails,
  expectedTPDetailsLoading,
  expectedTPDetailsSymbol,
  showExpectedTPDetailsDialog,
  onFetchExpectedTakeProfitSummary,
  onFetchExpectedTakeProfitDetails,
  onCloseDetailsDialog,
}: ExpectedTakeProfitTabProps) {
  const [sortField, setSortField] = useState<SortField | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');

  // Fetch expected take profit summary on mount (Strict Mode safe)
  const didFetchRef = useRef(false);
  useEffect(() => {
    if (didFetchRef.current) return;
    didFetchRef.current = true;

    onFetchExpectedTakeProfitSummary();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Empty deps: only run on mount. onFetchExpectedTakeProfitSummary is passed as prop from parent.

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
                  onClick={() => handleSort('net_qty')}
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
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
                >
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-slate-900 divide-y divide-gray-200 dark:divide-gray-700">
              {sortedSummary.map((item) => (
                <tr key={item.symbol} className="hover:bg-gray-50 dark:hover:bg-slate-800">
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-200">
                    {item.symbol}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {formatNumber(item.net_qty)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {formatNumber(item.position_value, '$')}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {formatNumber(item.covered_qty)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {formatNumber(item.uncovered_qty)}
                  </td>
                  <td className={`px-6 py-4 whitespace-nowrap text-sm font-semibold ${
                    (item.total_expected_profit || 0) >= 0 
                      ? 'text-green-600 dark:text-green-400' 
                      : 'text-red-600 dark:text-red-400'
                  }`}>
                    {formatNumber(item.total_expected_profit, '$')}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {item.current_price ? formatNumber(item.current_price, item.symbol) : 'N/A'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {item.coverage_ratio !== undefined && item.coverage_ratio !== null 
                      ? `${(item.coverage_ratio * 100).toFixed(1)}%` 
                      : 'N/A'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <button
                      onClick={() => onFetchExpectedTakeProfitDetails(item.symbol)}
                      className="text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300"
                    >
                      View Details
                    </button>
                  </td>
                </tr>
              ))}
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
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white">
                Expected TP Details: {expectedTPDetailsSymbol}
              </h3>
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
                {/* Summary Section */}
                <div className="bg-gray-50 dark:bg-slate-700 rounded-lg p-4">
                  <h4 className="text-lg font-semibold mb-3 text-gray-900 dark:text-white">Summary</h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div>
                      <div className="text-sm text-gray-600 dark:text-gray-400">Net Qty</div>
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
                      <div className={`text-lg font-semibold ${
                        (expectedTPDetails.total_expected_profit || 0) >= 0
                          ? 'text-green-600 dark:text-green-400'
                          : 'text-red-600 dark:text-red-400'
                      }`}>
                        {formatNumber(expectedTPDetails.total_expected_profit, '$')}
                      </div>
                    </div>
                    {expectedTPDetails.current_price !== undefined && (
                      <div>
                        <div className="text-sm text-gray-600 dark:text-gray-400">Current Price</div>
                        <div className="text-lg font-semibold text-gray-900 dark:text-white">
                          {formatNumber(expectedTPDetails.current_price, expectedTPDetailsSymbol || '')}
                        </div>
                      </div>
                    )}
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

                {/* Matched Lots Section */}
                {expectedTPDetails.matched_lots && expectedTPDetails.matched_lots.length > 0 ? (
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
                                {formatNumber(lot.buy_price, lot.symbol)}
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
                                <div className={`font-semibold ${
                                  (lot.expected_profit || 0) >= 0
                                    ? 'text-green-600 dark:text-green-400'
                                    : 'text-red-600 dark:text-red-400'
                                }`}>
                                  {formatNumber(lot.expected_profit, '$')}
                                </div>
                                {lot.expected_profit_pct !== undefined && (
                                  <div className="text-xs text-gray-500 dark:text-gray-400">
                                    ({lot.expected_profit_pct >= 0 ? '+' : ''}{lot.expected_profit_pct.toFixed(2)}%)
                                  </div>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
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



