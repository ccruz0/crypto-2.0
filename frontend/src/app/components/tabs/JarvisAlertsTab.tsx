'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  acknowledgeJarvisAlert,
  getJarvisAlerts,
  resolveJarvisAlert,
  type JarvisAlertSummary,
} from '@/app/api';

function SeverityBadge({ severity }: { severity: string }) {
  const normalized = severity.toUpperCase();
  const variant =
    normalized === 'CRITICAL'
      ? 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200'
      : normalized === 'WARNING'
        ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200'
        : 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200';
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${variant}`}>
      {normalized}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const variant =
    normalized === 'resolved'
      ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200'
      : normalized === 'acknowledged'
        ? 'bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-200'
        : normalized === 'suppressed'
          ? 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
          : 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200';
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${variant}`}>
      {status}
    </span>
  );
}

function formatTs(value: string | null | undefined): string {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

export default function JarvisAlertsTab() {
  const [alerts, setAlerts] = useState<JarvisAlertSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionId, setActionId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getJarvisAlerts(100);
      setAlerts(data.alerts || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load alerts');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 60_000);
    return () => clearInterval(timer);
  }, [refresh]);

  const handleAcknowledge = async (alertId: string) => {
    setActionId(alertId);
    try {
      await acknowledgeJarvisAlert(alertId);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to acknowledge alert');
    } finally {
      setActionId(null);
    }
  };

  const handleResolve = async (alertId: string) => {
    setActionId(alertId);
    try {
      await resolveJarvisAlert(alertId);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to resolve alert');
    } finally {
      setActionId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Jarvis Alerts</h2>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
            Autonomous read-only alerts from scheduled investigations — no patches, trades, or code changes.
          </p>
        </div>
        <button
          type="button"
          onClick={refresh}
          disabled={loading}
          className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="p-3 rounded border border-red-200 bg-red-50 text-red-800 text-sm dark:bg-red-900/20 dark:border-red-800 dark:text-red-200">
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-slate-700">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 dark:bg-slate-800 text-left text-xs uppercase text-gray-500 dark:text-gray-400">
            <tr>
              <th className="px-4 py-3">Severity</th>
              <th className="px-4 py-3">Title</th>
              <th className="px-4 py-3">Source</th>
              <th className="px-4 py-3">Occurrences</th>
              <th className="px-4 py-3">First seen</th>
              <th className="px-4 py-3">Last seen</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-slate-700 bg-white dark:bg-slate-900">
            {alerts.length === 0 && !loading && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-gray-500 dark:text-gray-400">
                  No alerts yet.
                </td>
              </tr>
            )}
            {alerts.map((alert) => (
              <tr key={alert.alert_id}>
                <td className="px-4 py-3">
                  <SeverityBadge severity={alert.severity} />
                </td>
                <td className="px-4 py-3 text-gray-900 dark:text-white max-w-xs truncate" title={alert.summary}>
                  {alert.title}
                </td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-300">{alert.source}</td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-300">{alert.occurrence_count}</td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-300 whitespace-nowrap">
                  {formatTs(alert.first_seen)}
                </td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-300 whitespace-nowrap">
                  {formatTs(alert.last_seen)}
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={alert.status} />
                </td>
                <td className="px-4 py-3 whitespace-nowrap space-x-2">
                  {alert.status === 'open' && (
                    <button
                      type="button"
                      disabled={actionId === alert.alert_id}
                      onClick={() => handleAcknowledge(alert.alert_id)}
                      className="text-xs px-2 py-1 rounded border border-purple-300 text-purple-700 hover:bg-purple-50 dark:border-purple-700 dark:text-purple-300"
                    >
                      Ack
                    </button>
                  )}
                  {alert.status !== 'resolved' && (
                    <button
                      type="button"
                      disabled={actionId === alert.alert_id}
                      onClick={() => handleResolve(alert.alert_id)}
                      className="text-xs px-2 py-1 rounded border border-green-300 text-green-700 hover:bg-green-50 dark:border-green-700 dark:text-green-300"
                    >
                      Resolve
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
