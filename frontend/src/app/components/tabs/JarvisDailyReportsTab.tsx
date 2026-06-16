'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { getJarvisDailyReports, type JarvisDailyReportSummary } from '@/app/api';

function formatTs(value: string | null | undefined): string {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

export default function JarvisDailyReportsTab() {
  const [reports, setReports] = useState<JarvisDailyReportSummary[]>([]);
  const [selected, setSelected] = useState<JarvisDailyReportSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getJarvisDailyReports(30);
      const items = data.reports || [];
      setReports(items);
      if (items.length > 0 && !selected) {
        setSelected(items[0]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load daily reports');
    } finally {
      setLoading(false);
    }
  }, [selected]);

  useEffect(() => {
    refresh();
  }, []);

  const summary = selected?.summary || {};

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Daily Health Reports</h2>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
            Automated daily summaries from autonomous investigations (08:00 UTC).
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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 space-y-2">
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Historical reports</h3>
          <div className="rounded-lg border border-gray-200 dark:border-slate-700 divide-y divide-gray-200 dark:divide-slate-700 max-h-96 overflow-y-auto">
            {reports.length === 0 && !loading && (
              <div className="p-4 text-sm text-gray-500 dark:text-gray-400">No reports yet.</div>
            )}
            {reports.map((report) => (
              <button
                key={report.report_id}
                type="button"
                onClick={() => setSelected(report)}
                className={`w-full text-left px-4 py-3 text-sm hover:bg-gray-50 dark:hover:bg-slate-800 ${
                  selected?.report_id === report.report_id
                    ? 'bg-blue-50 dark:bg-blue-900/20 border-l-2 border-blue-600'
                    : ''
                }`}
              >
                <div className="font-medium text-gray-900 dark:text-white">{report.report_date}</div>
                <div className="text-xs text-gray-500 dark:text-gray-400">
                  Generated {formatTs(report.generated_at)}
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="lg:col-span-2 space-y-4">
          {selected ? (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricCard label="Investigations" value={String(summary.investigations_executed ?? 0)} />
                <MetricCard label="Success rate" value={`${summary.success_rate_pct ?? 0}%`} />
                <MetricCard label="Failures" value={String(summary.failures ?? 0)} />
                <MetricCard label="Avg runtime" value={`${summary.average_runtime_ms ?? 0}ms`} />
                <MetricCard label="Warnings" value={String(summary.warnings ?? 0)} />
                <MetricCard label="Critical alerts" value={String(summary.critical_alerts ?? 0)} />
              </div>

              <div className="p-4 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800">
                <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                  Top recurring issues
                </h3>
                <ul className="space-y-2 text-sm text-gray-600 dark:text-gray-300">
                  {(summary.top_recurring_issues || []).length === 0 && (
                    <li className="text-gray-500">No recurring issues.</li>
                  )}
                  {(summary.top_recurring_issues || []).map(
                    (issue: { title?: string; occurrence_count?: number }, idx: number) => (
                      <li key={idx}>
                        {issue.title || 'Unknown'} ({issue.occurrence_count ?? 0}x)
                      </li>
                    ),
                  )}
                </ul>
              </div>

              <div className="p-4 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800">
                <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                  Generated summary
                </h3>
                <pre className="text-xs overflow-x-auto text-gray-600 dark:text-gray-300 whitespace-pre-wrap">
                  {JSON.stringify(summary, null, 2)}
                </pre>
              </div>
            </>
          ) : (
            <div className="p-8 text-center text-gray-500 dark:text-gray-400">
              Select a report to view metrics.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-4 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800">
      <div className="text-xs uppercase text-gray-500 dark:text-gray-400">{label}</div>
      <div className="text-lg font-semibold mt-1 text-gray-900 dark:text-white">{value}</div>
    </div>
  );
}
