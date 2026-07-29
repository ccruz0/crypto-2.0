'use client';

import React, { useMemo, useState } from 'react';
import type { OpenOrder, PortfolioAsset, TopCoin } from '@/app/api';
import { formatNumber } from '@/utils/formatting';
import {
  computePnLSummary,
  type CustomDateRange,
  type PnLPeriodPreset,
} from '@/utils/pnlSummary';

const PRESETS: { id: PnLPeriodPreset; label: string }[] = [
  { id: 'today', label: 'Today' },
  { id: '7d', label: '7d' },
  { id: '30d', label: '30d' },
  { id: 'month', label: 'Month' },
  { id: 'year', label: 'Year' },
  { id: 'custom', label: 'Custom' },
];

function todayInputValue(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function daysAgoInputValue(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function pnlClass(value: number): string {
  if (value > 0) return 'text-green-600 dark:text-green-400';
  if (value < 0) return 'text-red-600 dark:text-red-400';
  return 'text-gray-900 dark:text-white';
}

function formatSigned(value: number): string {
  const abs = formatNumber(Math.abs(value));
  if (value > 0) return `+${abs}`;
  if (value < 0) return `-${abs}`;
  return abs;
}

export interface PnLPanelProps {
  executedOrders: OpenOrder[];
  portfolioAssets?: PortfolioAsset[] | null;
  topCoins?: TopCoin[] | null;
}

export default function PnLPanel({
  executedOrders,
  portfolioAssets = null,
  topCoins = null,
}: PnLPanelProps) {
  const [preset, setPreset] = useState<PnLPeriodPreset>('30d');
  const [customRange, setCustomRange] = useState<CustomDateRange>({
    from: daysAgoInputValue(30),
    to: todayInputValue(),
  });

  const summary = useMemo(
    () =>
      computePnLSummary({
        executedOrders,
        portfolioAssets,
        topCoins,
        preset,
        customRange: preset === 'custom' ? customRange : null,
      }),
    [executedOrders, portfolioAssets, topCoins, preset, customRange]
  );

  return (
    <div className="mb-6" data-testid="pnl-panel">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3 mb-3">
        <div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">P&amp;L</h2>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
            Realized uses close date in the selected period. Unrealized is live mark-to-market
            (not filtered by period).
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="P&L period">
          {PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => setPreset(p.id)}
              className={`px-2.5 py-1 rounded text-sm font-medium transition-colors ${
                preset === p.id
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-600'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {preset === 'custom' && (
        <div className="flex flex-wrap items-center gap-3 mb-3 text-sm">
          <label className="flex items-center gap-2 text-gray-600 dark:text-gray-300">
            From
            <input
              type="date"
              value={customRange.from}
              onChange={(e) => setCustomRange((r) => ({ ...r, from: e.target.value }))}
              className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-gray-900 dark:text-white"
            />
          </label>
          <label className="flex items-center gap-2 text-gray-600 dark:text-gray-300">
            To
            <input
              type="date"
              value={customRange.to}
              onChange={(e) => setCustomRange((r) => ({ ...r, to: e.target.value }))}
              className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-gray-900 dark:text-white"
            />
          </label>
        </div>
      )}

      <div className="text-xs text-gray-500 dark:text-gray-400 mb-2">
        Period: {summary.period.label}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4 mb-4">
        <div className="bg-white dark:bg-gray-800 p-4 rounded shadow">
          <div className="text-sm text-gray-500">Realized</div>
          <div className="text-xs text-gray-400 mb-1">closes in period</div>
          <div className={`text-2xl font-bold ${pnlClass(summary.realizedPL)}`}>
            {formatSigned(summary.realizedPL)}
          </div>
        </div>
        <div className="bg-white dark:bg-gray-800 p-4 rounded shadow">
          <div className="text-sm text-gray-500">Unrealized</div>
          <div className="text-xs text-gray-400 mb-1">open lots · now</div>
          <div className={`text-2xl font-bold ${pnlClass(summary.unrealizedPL)}`}>
            {formatSigned(summary.unrealizedPL)}
          </div>
        </div>
        <div className="bg-white dark:bg-gray-800 p-4 rounded shadow">
          <div className="text-sm text-gray-500">Total</div>
          <div className="text-xs text-gray-400 mb-1">realized + unrealized</div>
          <div className={`text-2xl font-bold ${pnlClass(summary.totalPL)}`}>
            {formatSigned(summary.totalPL)}
          </div>
        </div>
        <div className="bg-white dark:bg-gray-800 p-4 rounded shadow">
          <div className="text-sm text-gray-500">Win rate</div>
          <div className="text-xs text-gray-400 mb-1">
            {summary.closeCount} close{summary.closeCount === 1 ? '' : 's'} in period
          </div>
          <div className="text-2xl font-bold text-gray-900 dark:text-white">
            {summary.winRate == null
              ? '—'
              : `${(summary.winRate * 100).toFixed(0)}%`}
          </div>
          {summary.closeCount > 0 && (
            <div className="text-xs text-gray-500 mt-1">
              {summary.winCount}W / {summary.closeCount - summary.winCount}L
            </div>
          )}
        </div>
        <div className="bg-white dark:bg-gray-800 p-4 rounded shadow col-span-2 md:col-span-1">
          <div className="text-sm text-gray-500 mb-2">Top symbols</div>
          {summary.topSymbols.length === 0 ? (
            <div className="text-sm text-gray-400">No closes in period</div>
          ) : (
            <ul className="space-y-1.5">
              {summary.topSymbols.map((row) => (
                <li
                  key={row.symbol}
                  className="flex items-center justify-between text-sm gap-2"
                >
                  <span className="font-medium text-gray-800 dark:text-gray-100 truncate">
                    {row.symbol}
                  </span>
                  <span className={`font-mono shrink-0 ${pnlClass(row.pnl)}`}>
                    {formatSigned(row.pnl)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
