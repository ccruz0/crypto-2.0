'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import Badge from '@/components/ui/Badge';
import Table from '@/components/ui/Table';
import {
  generateJarvisExecutiveReport,
  JarvisExecutiveReportSummary,
  listJarvisExecutiveReports,
} from '@/lib/api';

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function healthVariant(score: number): 'success' | 'danger' | 'warning' | 'neutral' {
  if (score >= 80) return 'success';
  if (score >= 60) return 'warning';
  return 'danger';
}

export default function JarvisExecutiveReportsPage() {
  const [reports, setReports] = useState<JarvisExecutiveReportSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadReports = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listJarvisExecutiveReports(20);
      setReports(data.reports || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load executive reports');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const report = await generateJarvisExecutiveReport();
      setError(null);
      await loadReports();
      window.location.href = `/jarvis/executive-reports/${report.report_id}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate report');
    } finally {
      setGenerating(false);
    }
  };

  useEffect(() => {
    loadReports();
  }, [loadReports]);

  const latest = reports[0];

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <div className="container mx-auto p-4 md:p-8 max-w-7xl">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Executive Reports</h1>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              Chief of Staff weekly priorities — read-only analysis, no autonomous execution.
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
              onClick={loadReports}
              disabled={loading}
              className="px-4 py-2 text-sm bg-gray-200 dark:bg-slate-700 rounded-md hover:bg-gray-300 dark:hover:bg-slate-600 disabled:opacity-50"
            >
              {loading ? 'Refreshing…' : 'Refresh'}
            </button>
            <button
              type="button"
              onClick={handleGenerate}
              disabled={generating}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
            >
              {generating ? 'Generating…' : 'Generate Report'}
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-300 bg-red-50 dark:bg-red-950/30 text-red-800 dark:text-red-200 px-4 py-3 text-sm">
            {error}
          </div>
        )}

        {latest && (
          <div className="mb-6 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-6">
            <div className="flex flex-wrap items-center gap-4">
              <div>
                <p className="text-xs uppercase text-gray-500 dark:text-gray-400">Latest Health Score</p>
                <p className="text-4xl font-bold tabular-nums text-gray-900 dark:text-white">
                  {latest.overall_health_score}
                </p>
              </div>
              <Badge variant={healthVariant(latest.overall_health_score)}>
                {latest.overall_health_score >= 80 ? 'healthy' : latest.overall_health_score >= 60 ? 'attention' : 'critical'}
              </Badge>
              <div className="flex-1 min-w-[200px]">
                <p className="text-xs uppercase text-gray-500 dark:text-gray-400">Top Priority</p>
                <p className="text-sm font-medium text-gray-900 dark:text-white">
                  {latest.top_priority_title || '—'}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase text-gray-500 dark:text-gray-400">Generated</p>
                <p className="text-sm text-gray-700 dark:text-gray-300">{formatTimestamp(latest.generated_at)}</p>
              </div>
              <Link
                href={`/jarvis/executive-reports/${latest.report_id}`}
                className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
              >
                View full report →
              </Link>
            </div>
          </div>
        )}

        {loading && reports.length === 0 ? (
          <div className="text-center py-8 text-gray-500">Loading executive reports…</div>
        ) : reports.length === 0 ? (
          <div className="text-center py-8 text-gray-500 border rounded-lg bg-white dark:bg-slate-800">
            No executive reports yet. Click &quot;Generate Report&quot; to create the first weekly priorities report.
          </div>
        ) : (
          <Table className="dark:bg-slate-800 dark:border-slate-700">
            <thead className="bg-gray-50 dark:bg-slate-900 text-left text-xs uppercase text-gray-500 dark:text-gray-400">
              <tr>
                <th className="px-4 py-3">Generated</th>
                <th className="px-4 py-3 text-center">Health Score</th>
                <th className="px-4 py-3">Top Priority</th>
                <th className="px-4 py-3 text-center">Priorities</th>
                <th className="px-4 py-3 text-center">Quick Wins</th>
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-slate-700">
              {reports.map((row) => (
                <tr key={row.report_id} className="hover:bg-gray-50 dark:hover:bg-slate-800/60">
                  <td className="px-4 py-3 whitespace-nowrap text-xs text-gray-600 dark:text-gray-300">
                    {formatTimestamp(row.generated_at)}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <Badge variant={healthVariant(row.overall_health_score)}>{row.overall_health_score}</Badge>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-900 dark:text-white max-w-xs truncate">
                    {row.top_priority_title || '—'}
                  </td>
                  <td className="px-4 py-3 text-center text-sm tabular-nums">{row.top_priority_count}</td>
                  <td className="px-4 py-3 text-center text-sm tabular-nums">{row.quick_win_count}</td>
                  <td className="px-4 py-3">
                    <Link
                      href={`/jarvis/executive-reports/${row.report_id}`}
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
