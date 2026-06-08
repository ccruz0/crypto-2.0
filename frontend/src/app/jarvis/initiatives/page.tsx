'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import Badge from '@/components/ui/Badge';
import Table from '@/components/ui/Table';
import { JarvisInitiativeSummary, listJarvisInitiatives } from '@/lib/api';

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

function statusVariant(status: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (status === 'completed') return 'success';
  if (status === 'blocked' || status === 'cancelled') return 'danger';
  if (status === 'active') return 'warning';
  return 'neutral';
}

function priorityVariant(priority: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (priority === 'critical') return 'danger';
  if (priority === 'high') return 'warning';
  return 'neutral';
}

function healthVariant(health: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (health === 'green') return 'success';
  if (health === 'red') return 'danger';
  if (health === 'yellow') return 'warning';
  return 'neutral';
}

export default function JarvisInitiativesPage() {
  const [initiatives, setInitiatives] = useState<JarvisInitiativeSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadInitiatives = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listJarvisInitiatives(50);
      setInitiatives(data.initiatives || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load initiatives');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadInitiatives();
  }, [loadInitiatives]);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <div className="container mx-auto p-4 md:p-8 max-w-7xl">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Initiatives</h1>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              Operating System layer — track what is being worked on, blocked, and overdue. Human-controlled only.
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
              onClick={loadInitiatives}
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

        {loading && initiatives.length === 0 ? (
          <div className="text-center py-8 text-gray-500">Loading initiatives…</div>
        ) : initiatives.length === 0 ? (
          <div className="text-center py-8 text-gray-500 border rounded-lg bg-white dark:bg-slate-800">
            No initiatives yet. Create initiatives via the API to track major ongoing objectives.
          </div>
        ) : (
          <Table className="dark:bg-slate-800 dark:border-slate-700">
            <thead className="bg-gray-50 dark:bg-slate-900 text-left text-xs uppercase text-gray-500 dark:text-gray-400">
              <tr>
                <th className="px-4 py-3">Title</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Priority</th>
                <th className="px-4 py-3 text-right">Progress</th>
                <th className="px-4 py-3">Health</th>
                <th className="px-4 py-3">Owner</th>
                <th className="px-4 py-3">Due date</th>
                <th className="px-4 py-3">Updated</th>
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-slate-700">
              {initiatives.map((row) => (
                <tr key={row.initiative_id} className="hover:bg-gray-50 dark:hover:bg-slate-800/60">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900 dark:text-white">
                    {row.title}
                    {row.is_overdue && (
                      <span className="ml-2 text-xs text-red-600 dark:text-red-400">
                        ({row.days_overdue}d overdue)
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={statusVariant(row.status)}>{row.status}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={priorityVariant(row.priority)}>{row.priority}</Badge>
                  </td>
                  <td className="px-4 py-3 text-right text-sm tabular-nums font-mono">
                    {row.progress_pct}%
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={healthVariant(row.health)}>{row.health}</Badge>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300">
                    {row.owner || '—'}
                  </td>
                  <td className="px-4 py-3 text-sm whitespace-nowrap text-gray-600 dark:text-gray-300">
                    {formatDate(row.target_date)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-xs text-gray-600 dark:text-gray-300">
                    {formatTimestamp(row.updated_at)}
                  </td>
                  <td className="px-4 py-3">
                    <Link
                      href={`/jarvis/initiatives/${row.initiative_id}`}
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
