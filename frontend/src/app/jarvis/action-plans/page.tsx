'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import Badge from '@/components/ui/Badge';
import Table from '@/components/ui/Table';
import { JarvisActionPlanSummary, listJarvisActionPlans } from '@/lib/api';

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function severityVariant(severity: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (severity === 'critical' || severity === 'high') return 'danger';
  if (severity === 'medium') return 'warning';
  return 'neutral';
}

function statusVariant(status: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (status === 'approved') return 'success';
  if (status === 'rejected') return 'danger';
  return 'warning';
}

export default function JarvisActionPlansPage() {
  const [plans, setPlans] = useState<JarvisActionPlanSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPlans = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listJarvisActionPlans(20);
      setPlans(data.plans || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load action plans');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPlans();
  }, [loadPlans]);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <div className="container mx-auto p-4 md:p-8 max-w-7xl">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Action Plans</h1>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              Remediation recommendations only — human approval required. No execution performed.
            </p>
          </div>
          <div className="flex gap-3">
            <Link
              href="/jarvis"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              ← Jarvis Tasks
            </Link>
            <button
              type="button"
              onClick={loadPlans}
              disabled={loading}
              className="px-4 py-2 text-sm bg-gray-200 dark:bg-slate-700 rounded-md hover:bg-gray-300 dark:hover:bg-slate-600 disabled:opacity-50"
            >
              {loading ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-300 bg-red-50 dark:bg-red-950/30 text-red-800 dark:text-red-200 px-4 py-3 text-sm">
            {error}
          </div>
        )}

        {loading && plans.length === 0 ? (
          <div className="text-center py-8 text-gray-500">Loading action plans…</div>
        ) : plans.length === 0 ? (
          <div className="text-center py-8 text-gray-500 border rounded-lg bg-white dark:bg-slate-800">
            No action plans yet. Generate one from an{' '}
            <Link href="/jarvis/audits" className="text-blue-600 dark:text-blue-400 hover:underline">
              AWS audit
            </Link>{' '}
            or{' '}
            <Link href="/jarvis/crypto-audits" className="text-blue-600 dark:text-blue-400 hover:underline">
              crypto audit
            </Link>
            .
          </div>
        ) : (
          <Table className="dark:bg-slate-800 dark:border-slate-700">
            <thead className="bg-gray-50 dark:bg-slate-900 text-left text-xs uppercase text-gray-500 dark:text-gray-400">
              <tr>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3">Severity</th>
                <th className="px-4 py-3 text-right">Est. savings/mo</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-slate-700">
              {plans.map((row) => (
                <tr key={row.plan_id} className="hover:bg-gray-50 dark:hover:bg-slate-800/60">
                  <td className="px-4 py-3 whitespace-nowrap text-xs text-gray-600 dark:text-gray-300">
                    {formatTimestamp(row.created_at)}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <span className="font-mono text-xs">{row.source_type || '—'}</span>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={severityVariant(row.severity)}>{row.severity}</Badge>
                  </td>
                  <td className="px-4 py-3 text-right text-sm tabular-nums font-mono">
                    ${row.estimated_savings_usd.toFixed(2)}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={statusVariant(row.status)}>{row.status}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <Link
                      href={`/jarvis/action-plans/${row.plan_id}`}
                      className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
                    >
                      View
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </div>
    </div>
  );
}
