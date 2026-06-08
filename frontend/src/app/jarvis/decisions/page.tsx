'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import Badge from '@/components/ui/Badge';
import Table from '@/components/ui/Table';
import {
  getJarvisDecisionAnalytics,
  JarvisDecisionIntelligence,
  JarvisDecisionSummary,
  listJarvisDecisions,
} from '@/lib/api';

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function decisionVariant(decision: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (decision === 'approved') return 'success';
  if (decision === 'rejected') return 'danger';
  return 'warning';
}

function outcomeVariant(outcome: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (outcome === 'successful') return 'success';
  if (outcome === 'unsuccessful') return 'danger';
  if (outcome === 'partial') return 'warning';
  return 'neutral';
}

export default function JarvisDecisionsPage() {
  const [decisions, setDecisions] = useState<JarvisDecisionSummary[]>([]);
  const [analytics, setAnalytics] = useState<JarvisDecisionIntelligence | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [decisionData, analyticsData] = await Promise.all([
        listJarvisDecisions(50),
        getJarvisDecisionAnalytics(),
      ]);
      setDecisions(decisionData.decisions || []);
      setAnalytics(analyticsData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load decisions');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <div className="container mx-auto p-4 md:p-8 max-w-7xl">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Decision Intelligence</h1>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              Jarvis learns from human decisions — no autonomous execution.
            </p>
          </div>
          <div className="flex gap-3">
            <Link
              href="/jarvis/executive"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Executive Dashboard
            </Link>
            <Link
              href="/jarvis"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              ← Jarvis Tasks
            </Link>
            <button
              type="button"
              onClick={load}
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

        {analytics && (
          <section className="mb-8">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Analytics</h2>
            <dl className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-4">
              <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                <dt className="text-xs uppercase text-gray-500">Success rate</dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums">{analytics.decision_success_rate}%</dd>
              </div>
              <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                <dt className="text-xs uppercase text-gray-500">Approved</dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums">{analytics.approved_count}</dd>
              </div>
              <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                <dt className="text-xs uppercase text-gray-500">Rejected</dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums">{analytics.rejected_count}</dd>
              </div>
              <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                <dt className="text-xs uppercase text-gray-500">Deferred</dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums">{analytics.deferred_count}</dd>
              </div>
              <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                <dt className="text-xs uppercase text-gray-500">Successful</dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums">{analytics.successful_outcomes}</dd>
              </div>
              <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                <dt className="text-xs uppercase text-gray-500">Repeated findings</dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums">{analytics.repeated_findings_count}</dd>
              </div>
            </dl>
            {(analytics.most_common_rejected_recommendation || analytics.most_successful_recommendation_type) && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                {analytics.most_common_rejected_recommendation && (
                  <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/20 p-3">
                    <p className="text-xs uppercase text-red-600 dark:text-red-400">Most rejected</p>
                    <p className="mt-1 text-red-900 dark:text-red-200">{analytics.most_common_rejected_recommendation}</p>
                  </div>
                )}
                {analytics.most_successful_recommendation_type && (
                  <div className="rounded-lg border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950/20 p-3">
                    <p className="text-xs uppercase text-green-600 dark:text-green-400">Most successful</p>
                    <p className="mt-1 text-green-900 dark:text-green-200">{analytics.most_successful_recommendation_type}</p>
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {loading && decisions.length === 0 ? (
          <div className="text-center py-8 text-gray-500">Loading decisions…</div>
        ) : decisions.length === 0 ? (
          <div className="text-center py-8 text-gray-500 border rounded-lg bg-white dark:bg-slate-800">
            No decisions recorded yet. Record decisions from{' '}
            <Link href="/jarvis/action-plans" className="text-blue-600 dark:text-blue-400 hover:underline">
              action plans
            </Link>
            .
          </div>
        ) : (
          <Table className="dark:bg-slate-800 dark:border-slate-700">
            <thead className="bg-gray-50 dark:bg-slate-900 text-left text-xs uppercase text-gray-500 dark:text-gray-400">
              <tr>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Decision</th>
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3">Outcome</th>
                <th className="px-4 py-3">Notes</th>
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-slate-700">
              {decisions.map((row) => (
                <tr key={row.decision_id} className="hover:bg-gray-50 dark:hover:bg-slate-800/60">
                  <td className="px-4 py-3 whitespace-nowrap text-xs text-gray-600 dark:text-gray-300">
                    {formatTimestamp(row.created_at)}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={decisionVariant(row.decision)}>{row.decision}</Badge>
                  </td>
                  <td className="px-4 py-3 text-xs font-mono text-gray-600 dark:text-gray-300">
                    {row.source_type || '—'}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={outcomeVariant(row.outcome)}>{row.outcome}</Badge>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-700 dark:text-gray-300 max-w-xs truncate">
                    {row.decision_reason || '—'}
                  </td>
                  <td className="px-4 py-3">
                    <Link
                      href={`/jarvis/decisions/${row.decision_id}`}
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
