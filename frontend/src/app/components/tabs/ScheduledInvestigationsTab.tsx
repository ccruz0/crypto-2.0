'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  getJarvisScheduledInvestigationReport,
  getJarvisScheduledInvestigations,
  type JarvisScheduledInvestigationReport,
  type JarvisScheduledInvestigationSchedule,
  type JarvisScheduledInvestigationTask,
} from '@/app/api';

function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const variant =
    normalized === 'completed'
      ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200'
      : normalized === 'failed' || normalized === 'cancelled'
        ? 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200'
        : normalized === 'running'
          ? 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200'
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

function formatDuration(ms: number): string {
  if (!ms || ms <= 0) return '—';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export default function ScheduledInvestigationsTab() {
  const [schedules, setSchedules] = useState<JarvisScheduledInvestigationSchedule[]>([]);
  const [tasks, setTasks] = useState<JarvisScheduledInvestigationTask[]>([]);
  const [scheduler, setScheduler] = useState<Record<string, unknown>>({});
  const [report, setReport] = useState<JarvisScheduledInvestigationReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, reportData] = await Promise.all([
        getJarvisScheduledInvestigations(50),
        getJarvisScheduledInvestigationReport(24),
      ]);
      setSchedules(data.schedules || []);
      setTasks(data.tasks || []);
      setScheduler(data.scheduler || {});
      setReport(reportData);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load scheduled investigations');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 60_000);
    return () => clearInterval(timer);
  }, [refresh]);

  const latestBySchedule = tasks.reduce<Record<string, JarvisScheduledInvestigationTask>>((acc, task) => {
    const existing = acc[task.schedule_id];
    if (!existing || (task.created_at || '') > (existing.created_at || '')) {
      acc[task.schedule_id] = task;
    }
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Scheduled Investigations</h2>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
            Autonomous read-only health checks — no patches, trades, or code changes.
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

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-4 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800">
          <div className="text-xs uppercase text-gray-500 dark:text-gray-400">Scheduler</div>
          <div className="text-lg font-semibold mt-1 text-gray-900 dark:text-white">
            {scheduler.scheduler_running ? 'Running' : 'Stopped'}
          </div>
          <div className="text-xs text-gray-500 mt-1">
            Interval: {String(scheduler.interval_seconds ?? 900)}s
          </div>
        </div>
        <div className="p-4 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800">
          <div className="text-xs uppercase text-gray-500 dark:text-gray-400">Success rate (24h)</div>
          <div className="text-lg font-semibold mt-1 text-green-700 dark:text-green-300">
            {report ? `${report.success_rate_pct.toFixed(1)}%` : '—'}
          </div>
        </div>
        <div className="p-4 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800">
          <div className="text-xs uppercase text-gray-500 dark:text-gray-400">Failure rate (24h)</div>
          <div className="text-lg font-semibold mt-1 text-red-700 dark:text-red-300">
            {report ? `${report.failure_rate_pct.toFixed(1)}%` : '—'}
          </div>
        </div>
        <div className="p-4 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800">
          <div className="text-xs uppercase text-gray-500 dark:text-gray-400">Avg runtime (24h)</div>
          <div className="text-lg font-semibold mt-1 text-gray-900 dark:text-white">
            {report ? formatDuration(report.average_runtime_ms) : '—'}
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 dark:border-slate-700 overflow-hidden">
        <div className="px-4 py-3 bg-gray-50 dark:bg-slate-800 border-b border-gray-200 dark:border-slate-700">
          <h3 className="font-medium text-gray-900 dark:text-white">Recurring schedules</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 dark:bg-slate-900/50 text-left text-xs uppercase text-gray-500">
              <tr>
                <th className="px-4 py-2">Title</th>
                <th className="px-4 py-2">Next run</th>
                <th className="px-4 py-2">Last run</th>
                <th className="px-4 py-2">Last status</th>
                <th className="px-4 py-2">Duration</th>
                <th className="px-4 py-2">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-slate-700">
              {schedules.map((schedule) => {
                const lastTask = latestBySchedule[schedule.schedule_id];
                return (
                  <tr key={schedule.schedule_id} className="bg-white dark:bg-slate-800">
                    <td className="px-4 py-3">
                      <div className="font-medium text-gray-900 dark:text-white">{schedule.title}</div>
                      <div className="text-xs text-gray-500 truncate max-w-xs">{schedule.objective}</div>
                    </td>
                    <td className="px-4 py-3 text-gray-700 dark:text-gray-300">{formatTs(schedule.next_run_at)}</td>
                    <td className="px-4 py-3 text-gray-700 dark:text-gray-300">{formatTs(schedule.last_run_at)}</td>
                    <td className="px-4 py-3">
                      {lastTask ? <StatusBadge status={lastTask.status} /> : <span className="text-gray-400">—</span>}
                    </td>
                    <td className="px-4 py-3 text-gray-700 dark:text-gray-300">
                      {lastTask ? formatDuration(lastTask.duration_ms) : '—'}
                    </td>
                    <td className="px-4 py-3 text-gray-600 dark:text-gray-400 max-w-md truncate">
                      {lastTask?.result_summary || lastTask?.error_message || '—'}
                    </td>
                  </tr>
                );
              })}
              {!loading && schedules.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-gray-500">
                    No schedules configured yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 dark:border-slate-700 overflow-hidden">
        <div className="px-4 py-3 bg-gray-50 dark:bg-slate-800 border-b border-gray-200 dark:border-slate-700">
          <h3 className="font-medium text-gray-900 dark:text-white">Recent task queue</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 dark:bg-slate-900/50 text-left text-xs uppercase text-gray-500">
              <tr>
                <th className="px-4 py-2">Schedule</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Started</th>
                <th className="px-4 py-2">Duration</th>
                <th className="px-4 py-2">Summary</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-slate-700">
              {tasks.map((task) => (
                <tr key={task.task_id} className="bg-white dark:bg-slate-800">
                  <td className="px-4 py-3 text-gray-900 dark:text-white">{task.schedule_id}</td>
                  <td className="px-4 py-3"><StatusBadge status={task.status} /></td>
                  <td className="px-4 py-3 text-gray-700 dark:text-gray-300">{formatTs(task.started_at || task.scheduled_at)}</td>
                  <td className="px-4 py-3 text-gray-700 dark:text-gray-300">{formatDuration(task.duration_ms)}</td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400 max-w-lg truncate">
                    {task.result_summary || task.error_message || '—'}
                  </td>
                </tr>
              ))}
              {!loading && tasks.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-gray-500">
                    No scheduled tasks yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
