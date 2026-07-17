/**
 * Portfolio Tab Component
 * Extracted from page.tsx for better organization
 */

import React, { useState, useMemo } from 'react';
import { PortfolioAsset } from '@/app/api';
import { formatNumber, formatDateTime } from '@/utils/formatting';
import { logger } from '@/utils/logger';

type SortField = 'coin' | 'balance' | 'value';
type SortDirection = 'asc' | 'desc';

interface PortfolioTabProps {
  portfolio: { assets: PortfolioAsset[]; total_value_usd: number; total_assets_usd?: number; total_collateral_usd?: number; total_borrowed_usd?: number; portfolio_value_source?: string } | null;
  portfolioLoading: boolean;
  portfolioError: string | null;
  totalBorrowed: number; // Legacy prop, prefer portfolio.total_borrowed_usd
  snapshotLastUpdated: Date | null;
  snapshotStale: boolean;
  snapshotStaleSeconds: number | null;
  botStatus: { is_running: boolean; status: 'running' | 'stopped'; reason: string | null; live_trading_enabled?: boolean; mode?: 'LIVE' | 'DRY_RUN'; kill_switch_on?: boolean } | null;
  togglingLiveTrading: boolean;
  isUpdating: boolean;
  topCoinsLoading: boolean;
  /** Open positions counted toward MAX_OPEN_ORDERS_TOTAL (same as trade guardrail). */
  openOrdersCount?: number | null;
  maxOpenOrders?: number | null;
  onToggleLiveTrading: () => Promise<void>;
  onRefreshPortfolio: () => Promise<void>;
}

export default function PortfolioTab({
  portfolio,
  portfolioLoading,
  portfolioError,
  totalBorrowed,
  snapshotLastUpdated,
  snapshotStale,
  snapshotStaleSeconds,
  botStatus,
  togglingLiveTrading,
  isUpdating,
  topCoinsLoading,
  openOrdersCount = null,
  maxOpenOrders = null,
  onToggleLiveTrading,
  onRefreshPortfolio,
}: PortfolioTabProps) {
  const [sortField, setSortField] = useState<SortField | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');

  // Sort assets
  const sortedAssets = useMemo(() => {
    if (!portfolio?.assets || portfolio.assets.length === 0) return [];
    if (!sortField) {
      // Default: sort by value (highest first)
      return [...portfolio.assets].sort((a, b) => (b.value_usd || 0) - (a.value_usd || 0));
    }

    return [...portfolio.assets].sort((a, b) => {
      let aVal: unknown = 0;
      let bVal: unknown = 0;

      switch (sortField) {
        case 'coin':
          aVal = (a.coin || '').toLowerCase();
          bVal = (b.coin || '').toLowerCase();
          break;
        case 'balance':
          aVal = a.balance || 0;
          bVal = b.balance || 0;
          break;
        case 'value':
          aVal = a.value_usd || 0;
          bVal = b.value_usd || 0;
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
  }, [portfolio?.assets, sortField, sortDirection]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  if (portfolioLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-gray-500 text-lg">Loading portfolio...</div>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-4 flex justify-between items-center">
        <div className="flex items-center gap-2">
          {snapshotLastUpdated && (
            <div className="text-sm text-gray-500">
              <span className="mr-2">🕐</span>
              Última actualización: {formatDateTime(snapshotLastUpdated)}
              {snapshotStaleSeconds !== null && (
                <span className="ml-2">({snapshotStaleSeconds}s ago)</span>
              )}
            </div>
          )}
          {snapshotStale && (
            <span className="text-xs bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded" title="Data may be stale (last update > 90s)">
              ⚠️ Data may be stale
            </span>
          )}
        </div>
        {botStatus && (
          <>
            <div className={`px-3 py-1 rounded-full text-xs font-semibold ${
              botStatus.is_running 
                ? 'bg-green-100 text-green-700' 
                : 'bg-red-100 text-red-700'
            }`} title={botStatus.reason || undefined}>
              {botStatus.is_running ? '🟢 Bot Activo' : '🔴 Bot Detenido'}
            </div>
            {botStatus.kill_switch_on && (
              <div className="px-3 py-1 rounded-full text-xs font-semibold bg-red-600 text-white" title="Kill Switch is ON - All trading is disabled">
                🛑 KILL SWITCH ON
              </div>
            )}
            <button
              onClick={onToggleLiveTrading}
              disabled={togglingLiveTrading || isUpdating || topCoinsLoading || portfolioLoading}
              className={`px-3 py-1 rounded-full text-xs font-semibold transition-colors ${
                botStatus.live_trading_enabled
                  ? 'bg-green-600 text-white hover:bg-green-700'
                  : 'bg-gray-400 text-white hover:bg-gray-500'
              }`}
            >
              {togglingLiveTrading ? '...' : botStatus.live_trading_enabled ? 'LIVE' : 'DRY RUN'}
            </button>
          </>
        )}
        <button
          onClick={onRefreshPortfolio}
          disabled={portfolioLoading}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-400"
        >
          {portfolioLoading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {portfolioError ? (
        <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded text-red-700">
          {portfolioError}
        </div>
      ) : !portfolio || !portfolio.assets || portfolio.assets.length === 0 ? (
        <div className="text-center py-12">
          <div className="text-gray-500 text-lg mb-2">No portfolio data available</div>
          <div className="text-gray-400 text-sm">The portfolio will appear here once you have assets in your account.</div>
        </div>
      ) : (
        <>
          <div className="mb-4">
            <h2 className="text-xl font-semibold mb-2">Portfolio Summary</h2>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
              <div className="bg-white dark:bg-gray-800 p-4 rounded shadow">
                <div className="text-sm text-gray-500">Total Value</div>
                <div className="text-xs text-gray-400 mb-1">Wallet Balance (after haircut)</div>
                <div className="text-2xl font-bold">{formatNumber(portfolio.total_value_usd)}</div>
                {portfolio.portfolio_value_source && (
                  <div className="text-xs text-gray-500 mt-1">
                    Source: {portfolio.portfolio_value_source === "exchange_margin_equity" 
                      ? "Exchange Wallet Balance" 
                      : "Derived (fallback)"}
                  </div>
                )}
              </div>
              {portfolio.total_assets_usd !== undefined && (
                <div className="bg-white dark:bg-gray-800 p-4 rounded shadow">
                  <div className="text-sm text-gray-500">Gross Assets</div>
                  <div className="text-xs text-gray-400 mb-1">(raw, before haircut)</div>
                  <div className="text-2xl font-bold text-blue-600">{formatNumber(portfolio.total_assets_usd)}</div>
                </div>
              )}
              {portfolio.total_collateral_usd !== undefined && (
                <div className="bg-white dark:bg-gray-800 p-4 rounded shadow">
                  <div className="text-sm text-gray-500">Collateral</div>
                  <div className="text-xs text-gray-400 mb-1">(after haircut)</div>
                  <div className="text-2xl font-bold text-green-600">{formatNumber(portfolio.total_collateral_usd)}</div>
                </div>
              )}
              {(() => {
                // Use portfolio.total_borrowed_usd if available, otherwise fall back to totalBorrowed prop
                const borrowedAmount = portfolio.total_borrowed_usd !== undefined 
                  ? portfolio.total_borrowed_usd 
                  : totalBorrowed;
                
                return borrowedAmount > 0 ? (
                  <div className="bg-white dark:bg-gray-800 p-4 rounded shadow">
                    <div className="text-sm text-gray-500">Borrowed</div>
                    <div className="text-xs text-gray-400 mb-1">(margin loans)</div>
                    <div className="text-2xl font-bold text-red-600">{formatNumber(borrowedAmount)}</div>
                  </div>
                ) : null;
              })()}
              {openOrdersCount !== null && openOrdersCount !== undefined && (
                <div
                  className={`p-4 rounded shadow ${
                    maxOpenOrders != null && openOrdersCount >= maxOpenOrders
                      ? 'bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-700'
                      : 'bg-white dark:bg-gray-800'
                  }`}
                  title={
                    maxOpenOrders != null
                      ? `Open positions counted toward the trade limit (${openOrdersCount}/${maxOpenOrders}). New entries are blocked at the limit.`
                      : 'Open positions counted toward the trade limit.'
                  }
                >
                  <div className="text-sm text-gray-500">Open Orders</div>
                  <div className="text-xs text-gray-400 mb-1">
                    {maxOpenOrders != null ? `limit ${maxOpenOrders}` : 'toward trade limit'}
                  </div>
                  <div
                    className={`text-2xl font-bold ${
                      maxOpenOrders != null && openOrdersCount >= maxOpenOrders
                        ? 'text-amber-700 dark:text-amber-300'
                        : 'text-indigo-600'
                    }`}
                  >
                    {maxOpenOrders != null
                      ? `${openOrdersCount} / ${maxOpenOrders}`
                      : openOrdersCount}
                  </div>
                  {maxOpenOrders != null && openOrdersCount >= maxOpenOrders && (
                    <div className="text-xs font-medium text-amber-700 dark:text-amber-300 mt-1">
                      Limit reached — no new orders
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div>
            <h2 className="text-xl font-semibold mb-2">Assets</h2>
            <div className="overflow-x-auto">
              <table className="min-w-full bg-white dark:bg-gray-800 rounded shadow">
                <thead className="bg-gray-50 dark:bg-gray-700">
                  <tr>
                    <th
                      className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-600 transition-colors"
                      onClick={() => handleSort('coin')}
                    >
                      <div className="flex items-center gap-1">
                        Coin {sortField === 'coin' && (sortDirection === 'asc' ? '↑' : '↓')}
                      </div>
                    </th>
                    <th
                      className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-600 transition-colors"
                      onClick={() => handleSort('balance')}
                    >
                      <div className="flex items-center gap-1">
                        Balance {sortField === 'balance' && (sortDirection === 'asc' ? '↑' : '↓')}
                      </div>
                    </th>
                    <th
                      className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-600 transition-colors"
                      onClick={() => handleSort('value')}
                    >
                      <div className="flex items-center gap-1">
                        Value (USD) {sortField === 'value' && (sortDirection === 'asc' ? '↑' : '↓')}
                      </div>
                    </th>
                    <th
                      className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
                      title="Unrealized profit/loss vs weighted-average buy price. Shows — when no tracked buy orders exist."
                    >
                      <div className="flex items-center gap-1">P&amp;L %</div>
                    </th>
                    <th
                      className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
                      title="Unrealized net profit in USD vs cost basis. Shows — when no tracked buy orders exist."
                    >
                      <div className="flex items-center gap-1">Net Profit (USD)</div>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                  {sortedAssets.map((asset) => {
                    const hasCostBasis =
                      !asset.cost_basis_unknown &&
                      asset.pnl_pct !== null && asset.pnl_pct !== undefined &&
                      asset.net_profit_usd !== null && asset.net_profit_usd !== undefined;
                    const pnlPositive = hasCostBasis && (asset.pnl_pct as number) >= 0;
                    const pnlColorClass = pnlPositive ? 'text-green-600' : 'text-red-600';
                    const isShort = (asset.balance ?? 0) < 0;
                    const balanceColorClass = isShort ? 'text-red-600 font-medium' : 'text-gray-500 dark:text-gray-300';
                    return (
                      <tr key={asset.coin} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                        <td className="px-4 py-3 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white">
                          {asset.coin}
                          {isShort && (
                            <span className="ml-2 text-xs font-semibold uppercase text-red-600 bg-red-50 dark:bg-red-900/30 px-1.5 py-0.5 rounded">
                              Short
                            </span>
                          )}
                        </td>
                        <td className={`px-4 py-3 whitespace-nowrap text-sm ${balanceColorClass}`}>{formatNumber(asset.balance)}</td>
                        <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900 dark:text-white">{formatNumber(asset.value_usd)}</td>
                        <td className="px-4 py-3 whitespace-nowrap text-sm">
                          {hasCostBasis ? (
                            <span className={`font-medium ${pnlColorClass}`}>
                              {pnlPositive ? '+' : ''}{(asset.pnl_pct as number).toFixed(2)}%
                            </span>
                          ) : (
                            <span className="text-gray-400" title="No tracked buy orders — cost basis unknown">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-sm">
                          {hasCostBasis ? (
                            <span className={`font-medium ${pnlColorClass}`}>
                              {pnlPositive ? '+' : '-'}{formatNumber(Math.abs(asset.net_profit_usd as number))}
                            </span>
                          ) : (
                            <span className="text-gray-400" title="No tracked buy orders — cost basis unknown">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}



