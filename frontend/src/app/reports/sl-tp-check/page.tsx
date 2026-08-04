'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { createProtectionSmart } from '@/app/api';
import { getApiUrl } from '@/lib/environment';

interface MissingPosition {
  symbol: string;
  currency?: string;
  balance?: number;
  has_sl?: boolean;
  has_tp?: boolean;
  sl_price?: number | null;
  tp_price?: number | null;
  order_id?: string | null;
  quantity?: number | null;
  side?: string | null;
  entry_price?: number | null;
}

interface SlTpCheckReport {
  workflow?: string;
  checked_at?: string | null;
  total_positions?: number;
  missing_count?: number;
  positions_missing?: MissingPosition[];
  oco_issues?: Record<string, unknown>;
  reminder_sent?: boolean;
  error?: string | null;
}

function formatNumber(value: number | null | undefined, digits = 4): string {
  if (value == null || Number.isNaN(value)) return '—';
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function formatTimestamp(ts: string | null | undefined): string {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return ts;
    return d.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      timeZoneName: 'short',
    });
  } catch {
    return ts;
  }
}

export default function SlTpCheckReportPage() {
  const [report, setReport] = useState<SlTpCheckReport | null>(null);
  const [storedAt, setStoredAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creatingKey, setCreatingKey] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const fetchReport = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const apiUrl = getApiUrl();
      const response = await fetch(`${apiUrl}/monitoring/reports/sl-tp-check/latest`, {
        cache: 'no-store',
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      const data = await response.json();
      if (data.status === 'not_found') {
        setReport(null);
        setStoredAt(null);
        setError(data.message || 'No SL/TP Check report available yet. Run the workflow first.');
        return;
      }
      if (data.status === 'success' && data.report) {
        setReport(data.report as SlTpCheckReport);
        setStoredAt(data.stored_at || null);
      } else {
        setError('Invalid report format received from server.');
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      setError(errorMsg);
      console.error('Failed to fetch SL/TP check report:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchReport();
  }, [fetchReport]);

  const handleCreate = async (
    pos: MissingPosition,
    opts: { create_sl: boolean; create_tp: boolean },
  ) => {
    if (!pos.order_id) {
      setActionMessage(`No filled entry order found for ${pos.symbol} — open Expected TP Details to create protection.`);
      return;
    }
    const key = `${pos.order_id}:${opts.create_sl ? 'sl' : ''}${opts.create_tp ? 'tp' : ''}`;
    setCreatingKey(key);
    setActionMessage(null);
    try {
      const result = await createProtectionSmart({
        order_id: pos.order_id,
        create_sl: opts.create_sl,
        create_tp: opts.create_tp,
        quantity: pos.quantity ?? undefined,
      });
      const created = (result.created || []).map((c) => c.role).join(', ');
      const errText = (result.errors || [])
        .map((e) => `${e.role}: ${JSON.stringify(e.error)}`)
        .join('; ');
      if (result.ok && (result.created || []).length > 0) {
        setActionMessage(`${pos.symbol}: created ${created}`);
      } else if (result.ok) {
        setActionMessage(
          `${pos.symbol}: ${result.message || 'Protection already exists — no new orders placed.'}`,
        );
      } else {
        setActionMessage(
          `${pos.symbol}: failed — ${result.message || 'no orders created'}${errText ? ` | ${errText}` : ''}`,
        );
      }
      await fetchReport();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setActionMessage(
        msg.includes('Invalid API key') || msg.includes('401')
          ? `Auth failed (${msg}). If this persists after deploy, contact ops.`
          : `${pos.symbol}: ${msg}`,
      );
    } finally {
      setCreatingKey(null);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 py-8">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4" />
            <p className="text-gray-500">Loading SL/TP Check report...</p>
          </div>
        </div>
      </div>
    );
  }

  if (error && !report) {
    return (
      <div className="min-h-screen bg-gray-50 py-8">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="bg-white rounded-lg shadow p-6">
            <h1 className="text-2xl font-bold text-gray-900 mb-4">SL/TP Check Report</h1>
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
              <p className="text-yellow-800">{error}</p>
            </div>
            <div className="mt-4 flex gap-4 text-sm">
              <a href="/" className="text-blue-600 hover:text-blue-800 underline">
                ← Back to Dashboard
              </a>
              <button
                type="button"
                onClick={() => fetchReport()}
                className="text-blue-600 hover:text-blue-800 underline"
              >
                Retry
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const positions = Array.isArray(report?.positions_missing) ? report!.positions_missing! : [];

  return (
    <div className="min-h-screen bg-gray-50 py-8">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="mb-6 flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">SL/TP Check Report</h1>
            <p className="text-sm text-gray-500 mt-1">
              Positions missing Stop Loss and/or Take Profit protection
            </p>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <button
              type="button"
              onClick={() => fetchReport()}
              className="px-3 py-1.5 bg-gray-100 text-gray-700 rounded hover:bg-gray-200"
            >
              Refresh
            </button>
            <a href="/" className="text-blue-600 hover:text-blue-800 underline">
              ← Back to Dashboard
            </a>
          </div>
        </div>

        <div className="bg-white rounded-lg shadow mb-6 p-6 grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div>
            <div className="text-xs uppercase text-gray-500">Checked at</div>
            <div className="text-sm font-medium text-gray-900">
              {formatTimestamp(report?.checked_at || storedAt)}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase text-gray-500">Open positions scanned</div>
            <div className="text-2xl font-bold text-gray-900">{report?.total_positions ?? 0}</div>
          </div>
          <div>
            <div className="text-xs uppercase text-gray-500">Missing protection</div>
            <div className="text-2xl font-bold text-gray-900">{report?.missing_count ?? positions.length}</div>
          </div>
        </div>

        {report?.error && (
          <div className="mb-6 bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-800">
            Workflow error: {report.error}
          </div>
        )}

        {actionMessage && (
          <div
            className={`mb-6 rounded-lg border p-4 text-sm ${
              actionMessage.toLowerCase().includes('fail') ||
              actionMessage.toLowerCase().includes('auth')
                ? 'bg-red-50 border-red-200 text-red-800'
                : 'bg-emerald-50 border-emerald-200 text-emerald-800'
            }`}
          >
            {actionMessage}
          </div>
        )}

        <div className="bg-white rounded-lg shadow border border-gray-200">
          <div className="p-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">Unprotected positions</h2>
            <p className="text-xs text-gray-500 mt-1">
              Separate Create SL / Create TP actions call the same create-protection-smart path as Expected TP.
            </p>
          </div>
          {positions.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              No positions missing SL/TP in the latest check.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Balance</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Entry order</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">SL</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">TP</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {positions.map((pos) => {
                    const needSl = !pos.has_sl;
                    const needTp = !pos.has_tp;
                    const slKey = `${pos.order_id || pos.symbol}:sl`;
                    const tpKey = `${pos.order_id || pos.symbol}:tp`;
                    const busy = creatingKey != null;
                    return (
                      <tr key={`${pos.symbol}-${pos.order_id || 'no-order'}`} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-sm font-medium text-gray-900">{pos.symbol}</td>
                        <td className="px-4 py-3 text-sm text-gray-700">{formatNumber(pos.balance)}</td>
                        <td className="px-4 py-3 text-sm font-mono text-xs text-gray-700">
                          {pos.order_id || (
                            <span className="text-amber-700" title="Cannot create via smart path without entry order">
                              No entry order
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-sm">
                          {pos.has_sl ? (
                            <span className="text-green-700 font-medium">OK</span>
                          ) : (
                            <span className="text-orange-700 font-medium">Missing</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-sm">
                          {pos.has_tp ? (
                            <span className="text-green-700 font-medium">OK</span>
                          ) : (
                            <span className="text-orange-700 font-medium">Missing</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="inline-flex flex-wrap justify-end gap-2">
                            {needSl && (
                              <button
                                type="button"
                                disabled={busy || !pos.order_id}
                                title={
                                  pos.order_id
                                    ? 'Create Stop Loss via create-protection-smart'
                                    : 'No filled entry order linked'
                                }
                                onClick={() => handleCreate(pos, { create_sl: true, create_tp: false })}
                                className={`px-2 py-1 rounded text-xs font-semibold ${
                                  creatingKey === slKey
                                    ? 'bg-gray-300 text-gray-500 cursor-wait'
                                    : !pos.order_id
                                      ? 'bg-gray-200 text-gray-400 cursor-not-allowed'
                                      : 'bg-emerald-600 text-white hover:bg-emerald-700'
                                }`}
                              >
                                {creatingKey === slKey ? 'Creating…' : 'Create SL'}
                              </button>
                            )}
                            {needTp && (
                              <button
                                type="button"
                                disabled={busy || !pos.order_id}
                                title={
                                  pos.order_id
                                    ? 'Create Take Profit via create-protection-smart'
                                    : 'No filled entry order linked'
                                }
                                onClick={() => handleCreate(pos, { create_sl: false, create_tp: true })}
                                className={`px-2 py-1 rounded text-xs font-semibold ${
                                  creatingKey === tpKey
                                    ? 'bg-gray-300 text-gray-500 cursor-wait'
                                    : !pos.order_id
                                      ? 'bg-gray-200 text-gray-400 cursor-not-allowed'
                                      : 'bg-emerald-600 text-white hover:bg-emerald-700'
                                }`}
                              >
                                {creatingKey === tpKey ? 'Creating…' : 'Create TP'}
                              </button>
                            )}
                            {!needSl && !needTp && (
                              <span className="text-xs text-gray-400">OK</span>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
