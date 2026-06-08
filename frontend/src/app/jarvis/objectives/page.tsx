'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import Badge from '@/components/ui/Badge';
import Table from '@/components/ui/Table';
import {
  JarvisKrRefreshRunSummary,
  JarvisObjectiveSummary,
  listJarvisKrRefreshRuns,
  listJarvisObjectives,
  refreshJarvisKeyResults,
  seedJarvisObjectives,
} from '@/lib/api';

function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString();
}

function healthVariant(health: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (health === 'green') return 'success';
  if (health === 'red') return 'danger';
  if (health === 'yellow') return 'warning';
  return 'neutral';
}

function statusVariant(status: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (status === 'completed') return 'success';
  if (status === 'cancelled') return 'neutral';
  if (status === 'active') return 'warning';
  return 'neutral';
}

export default function JarvisObjectivesPage() {
  const [objectives, setObjectives] = useState<JarvisObjectiveSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seedMessage, setSeedMessage] = useState<string | null>(null);
  const [refreshingKr, setRefreshingKr] = useState(false);
  const [krRefreshMessage, setKrRefreshMessage] = useState<string | null>(null);
  const [lastKrRefresh, setLastKrRefresh] = useState<JarvisKrRefreshRunSummary | null>(null);

  const loadKrRefreshStatus = useCallback(async () => {
    try {
      const data = await listJarvisKrRefreshRuns(1);
      setLastKrRefresh(data.runs?.[0] ?? null);
    } catch {
      setLastKrRefresh(null);
    }
  }, []);

  const loadObjectives = useCallback(async () => {
    setLoading(true);
    try {
      const [data] = await Promise.all([listJarvisObjectives(100), loadKrRefreshStatus()]);
      setObjectives(data.objectives || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load objectives');
    } finally {
      setLoading(false);
    }
  }, [loadKrRefreshStatus]);

  const handleKrRefresh = useCallback(async () => {
    setRefreshingKr(true);
    setKrRefreshMessage(null);
    try {
      const result = await refreshJarvisKeyResults();
      setKrRefreshMessage(
        `KR refresh complete: ${result.updated_count} updated, ${result.failed_count} failed.`,
      );
      await loadObjectives();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to refresh KR metrics');
    } finally {
      setRefreshingKr(false);
    }
  }, [loadObjectives]);

  const handleSeed = useCallback(async () => {
    setSeeding(true);
    setSeedMessage(null);
    try {
      const result = await seedJarvisObjectives();
      setSeedMessage(`Seeded ${result.count} objective(s).`);
      await loadObjectives();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to seed objectives');
    } finally {
      setSeeding(false);
    }
  }, [loadObjectives]);

  useEffect(() => {
    loadObjectives();
  }, [loadObjectives]);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <div className="container mx-auto p-4 md:p-8 max-w-7xl">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Strategic Objectives</h1>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              Track progress toward strategic goals — read-only planning, human-controlled.
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
              onClick={handleKrRefresh}
              disabled={refreshingKr}
              className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
            >
              {refreshingKr ? 'Refreshing KR…' : 'Refresh KR Metrics'}
            </button>
            <button
              type="button"
              onClick={handleSeed}
              disabled={seeding}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
            >
              {seeding ? 'Seeding…' : 'Seed sample objectives'}
            </button>
            <button
              type="button"
              onClick={loadObjectives}
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

        {seedMessage && (
          <div className="mb-4 rounded border border-green-300 bg-green-50 dark:bg-green-950/30 text-green-800 dark:text-green-200 px-4 py-3 text-sm">
            {seedMessage}
          </div>
        )}

        {krRefreshMessage && (
          <div className="mb-4 rounded border border-indigo-300 bg-indigo-50 dark:bg-indigo-950/30 text-indigo-800 dark:text-indigo-200 px-4 py-3 text-sm">
            {krRefreshMessage}
          </div>
        )}

        {lastKrRefresh && (
          <div className="mb-4 rounded border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
            <span className="font-medium">Last KR refresh:</span>{' '}
            {formatDate(lastKrRefresh.created_at)} · updated {lastKrRefresh.updated_count} · failed{' '}
            {lastKrRefresh.failed_count}
          </div>
        )}

        {loading && objectives.length === 0 ? (
          <div className="text-center py-8 text-gray-500">Loading objectives…</div>
        ) : objectives.length === 0 ? (
          <div className="text-center py-8 text-gray-500 border rounded-lg bg-white dark:bg-slate-800">
            No objectives yet. Seed sample objectives or create via the API.
          </div>
        ) : (
          <Table className="dark:bg-slate-800 dark:border-slate-700">
            <thead className="bg-gray-50 dark:bg-slate-900 text-left text-xs uppercase text-gray-500 dark:text-gray-400">
              <tr>
                <th className="px-4 py-3">Objective</th>
                <th className="px-4 py-3 text-right">Progress</th>
                <th className="px-4 py-3">Health</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Alignment</th>
                <th className="px-4 py-3">Owner</th>
                <th className="px-4 py-3">Due date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-slate-700">
              {objectives.map((item) => (
                <tr key={item.objective_id} className="hover:bg-gray-50 dark:hover:bg-slate-700/50">
                  <td className="px-4 py-3">
                    <Link
                      href={`/jarvis/objectives/${item.objective_id}`}
                      className="text-blue-600 dark:text-blue-400 hover:underline font-medium"
                    >
                      {item.title}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">{item.progress_pct}%</td>
                  <td className="px-4 py-3">
                    <Badge variant={healthVariant(item.health)}>{item.health}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={statusVariant(item.status)}>{item.status}</Badge>
                  </td>
                  <td className="px-4 py-3 text-sm">{item.alignment_status}</td>
                  <td className="px-4 py-3 text-sm">{item.owner || '—'}</td>
                  <td className="px-4 py-3 text-sm tabular-nums">
                    {formatDate(item.target_date)}
                    {item.is_overdue && (
                      <span className="ml-1 text-red-600 dark:text-red-400 text-xs">overdue</span>
                    )}
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
