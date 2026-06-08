'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import Badge from '@/components/ui/Badge';
import Table from '@/components/ui/Table';
import {
  generateJarvisFollowups,
  JarvisFollowupSummary,
  listJarvisFollowups,
} from '@/lib/api';

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString();
}

function severityVariant(severity: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (severity === 'critical') return 'danger';
  if (severity === 'high') return 'warning';
  if (severity === 'low') return 'success';
  return 'neutral';
}

function statusVariant(status: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (status === 'resolved') return 'success';
  if (status === 'dismissed') return 'neutral';
  if (status === 'acknowledged') return 'warning';
  return 'danger';
}

function sourceLabel(sourceType: string): string {
  return sourceType.replace(/_/g, ' ');
}

export default function JarvisFollowupsPage() {
  const [followups, setFollowups] = useState<JarvisFollowupSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generateMessage, setGenerateMessage] = useState<string | null>(null);

  const loadFollowups = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listJarvisFollowups(100);
      setFollowups(data.followups || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load follow-ups');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setGenerateMessage(null);
    try {
      const result = await generateJarvisFollowups(false);
      setGenerateMessage(
        `Generated ${result.followups_touched} follow-up(s). Open: ${result.summary?.open_followups ?? 0}`,
      );
      await loadFollowups();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate follow-ups');
    } finally {
      setGenerating(false);
    }
  }, [loadFollowups]);

  useEffect(() => {
    loadFollowups();
  }, [loadFollowups]);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <div className="container mx-auto p-4 md:p-8 max-w-7xl">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Follow-ups</h1>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              Management reminders — read-only, no autonomous execution.
            </p>
          </div>
          <div className="flex gap-3">
            <Link
              href="/jarvis"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              ← Jarvis Tasks
            </Link>
            <Link
              href="/jarvis/executive"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Executive Dashboard
            </Link>
            <button
              type="button"
              onClick={handleGenerate}
              disabled={generating}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
            >
              {generating ? 'Generating…' : 'Generate follow-ups'}
            </button>
            <button
              type="button"
              onClick={loadFollowups}
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

        {generateMessage && (
          <div className="mb-4 rounded border border-green-300 bg-green-50 dark:bg-green-950/30 text-green-800 dark:text-green-200 px-4 py-3 text-sm">
            {generateMessage}
          </div>
        )}

        {loading && followups.length === 0 ? (
          <div className="text-center py-8 text-gray-500">Loading follow-ups…</div>
        ) : followups.length === 0 ? (
          <div className="text-center py-8 text-gray-500 border rounded-lg bg-white dark:bg-slate-800">
            No follow-ups yet. Click &quot;Generate follow-ups&quot; to detect overdue initiatives, pending decisions, and stale audits.
          </div>
        ) : (
          <Table className="dark:bg-slate-800 dark:border-slate-700">
            <thead className="bg-gray-50 dark:bg-slate-900 text-left text-xs uppercase text-gray-500 dark:text-gray-400">
              <tr>
                <th className="px-4 py-3">Severity</th>
                <th className="px-4 py-3">Title</th>
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Due date</th>
                <th className="px-4 py-3 text-right">Reminders</th>
                <th className="px-4 py-3">Last reminded</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-slate-700">
              {followups.map((item) => (
                <tr key={item.followup_id} className="hover:bg-gray-50 dark:hover:bg-slate-700/50">
                  <td className="px-4 py-3">
                    <Badge variant={severityVariant(item.severity)}>{item.severity}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <Link
                      href={`/jarvis/followups/${item.followup_id}`}
                      className="text-blue-600 dark:text-blue-400 hover:underline font-medium"
                    >
                      {item.title}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400 capitalize">
                    {sourceLabel(item.source_type)}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={statusVariant(item.status)}>{item.status}</Badge>
                  </td>
                  <td className="px-4 py-3 text-sm tabular-nums">
                    {formatDate(item.due_date)}
                    {item.is_overdue && (
                      <span className="ml-1 text-red-600 dark:text-red-400 text-xs">overdue</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">{item.reminder_count}</td>
                  <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                    {formatTimestamp(item.last_reminded_at)}
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
