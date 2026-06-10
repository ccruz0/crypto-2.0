'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  getAgentStatus,
  getAgentOpsRecovery,
  getAgentOpsFailedInvestigations,
  getAgentOpsActiveTasks,
  getAgentOpsSmokeChecks,
  getAgentOpsDeployTracker,
  getAgentOpsCursorBridgeEvents,
  getAgentOpsCursorBridgeDiagnostics,
  type AgentStatus,
  type AgentOpsRecovery,
  type AgentOpsFailedInvestigations,
  type AgentOpsActiveTasks,
  type AgentOpsSmokeChecks,
  type AgentOpsDeployTracker,
  type AgentOpsCursorBridgeEvents,
  type AgentOpsCursorBridgeDiagnostics,
} from '@/app/api';

const POLL_INTERVAL_MS = 45000; // 45 seconds
const STALE_THRESHOLD_MS = 15 * 60 * 1000; // 15 min for patching/awaiting
const STALE_DEPLOYING_MS = 10 * 60 * 1000; // 10 min for deploying

function StatusBadge({
  variant,
  children,
  title,
}: {
  variant: 'success' | 'danger' | 'warning' | 'neutral';
  children: React.ReactNode;
  title?: string;
}) {
  const classes = {
    success: 'bg-green-100 text-green-800 border-green-200 dark:bg-green-900/40 dark:text-green-200 dark:border-green-700',
    danger: 'bg-red-100 text-red-800 border-red-200 dark:bg-red-900/40 dark:text-red-200 dark:border-red-700',
    warning: 'bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-900/40 dark:text-amber-200 dark:border-amber-700',
    neutral: 'bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-700/40 dark:text-gray-300 dark:border-gray-600',
  };
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border ${classes[variant]}`}
      title={title}
    >
      {children}
    </span>
  );
}

function formatTs(ts: string): string {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    return isNaN(d.getTime()) ? ts : d.toLocaleString(undefined, {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return ts;
  }
}

function EventList({
  title,
  items,
  emptyMsg,
  renderItem,
  headerBadge,
}: {
  title: string;
  items: Array<{ timestamp: string; event_type: string; task_id: string | null; task_title: string | null; details: Record<string, unknown> }>;
  emptyMsg: string;
  renderItem: (item: (typeof items)[0]) => React.ReactNode;
  headerBadge?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
      <h3 className="px-4 py-2 text-sm font-semibold text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center gap-2">
        {title}
        {headerBadge}
      </h3>
      <div className="max-h-48 overflow-y-auto">
        {items.length === 0 ? (
          <p className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">{emptyMsg}</p>
        ) : (
          <ul className="divide-y divide-gray-200 dark:divide-gray-700">
            {items.map((item, i) => (
              <li key={i} className="px-4 py-2 text-sm">
                {renderItem(item)}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function TaskTable({
  title,
  tasks,
  badgeVariant,
  taskIdToLastEventTs,
  staleThresholdMs,
}: {
  title: string;
  tasks: Array<{ id?: string | null; task?: string | null; status?: string | null; priority?: string | null }>;
  badgeVariant: 'success' | 'danger' | 'warning' | 'neutral';
  taskIdToLastEventTs?: Map<string, number>;
  staleThresholdMs?: number;
}) {
  const badgeClasses = {
    success: 'bg-green-100 text-green-800 border-green-200 dark:bg-green-900/40 dark:text-green-200 dark:border-green-700',
    danger: 'bg-red-100 text-red-800 border-red-200 dark:bg-red-900/40 dark:text-red-200 dark:border-red-700',
    warning: 'bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-900/40 dark:text-amber-200 dark:border-amber-700',
    neutral: 'bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-700/40 dark:text-gray-300 dark:border-gray-600',
  };
  const now = Date.now();
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
      <h3 className="px-4 py-2 text-sm font-semibold text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center gap-2">
        <span>{title}</span>
        <span className={`px-2 py-0.5 rounded-full text-xs font-semibold border ${badgeClasses[badgeVariant]}`}>
          {tasks.length}
        </span>
      </h3>
      {tasks.length === 0 ? (
        <p className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">None</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-700">
                <th className="px-4 py-2 text-left text-gray-600 dark:text-gray-400">Task</th>
                <th className="px-4 py-2 text-left text-gray-600 dark:text-gray-400">Status</th>
                <th className="px-4 py-2 text-left text-gray-600 dark:text-gray-400">Priority</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t, i) => {
                const taskId = (t.id ?? '').toString().trim();
                const lastTs = taskId && taskIdToLastEventTs?.get(taskId);
                const isStale =
                  staleThresholdMs &&
                  lastTs &&
                  now - lastTs > staleThresholdMs;
                return (
                  <tr
                    key={t.id ?? `row-${i}`}
                    className={`border-b border-gray-100 dark:border-gray-800 ${
                      isStale ? 'bg-amber-50 dark:bg-amber-900/20 border-l-2 border-l-amber-400 dark:border-l-amber-600' : ''
                    }`}
                    title={isStale ? `Last activity ${Math.round((now - lastTs) / 60000)} min ago` : undefined}
                  >
                    <td className="px-4 py-2 text-gray-800 dark:text-gray-200">{t.task ?? '(untitled)'}</td>
                    <td className="px-4 py-2 text-gray-600 dark:text-gray-400">{t.status ?? '—'}</td>
                    <td className="px-4 py-2 text-gray-600 dark:text-gray-400">{t.priority ?? '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function AgentOpsTab({ embedded = false }: { embedded?: boolean }) {
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [recovery, setRecovery] = useState<AgentOpsRecovery | null>(null);
  const [failed, setFailed] = useState<AgentOpsFailedInvestigations | null>(null);
  const [active, setActive] = useState<AgentOpsActiveTasks | null>(null);
  const [smoke, setSmoke] = useState<AgentOpsSmokeChecks | null>(null);
  const [deploy, setDeploy] = useState<AgentOpsDeployTracker | null>(null);
  const [bridge, setBridge] = useState<AgentOpsCursorBridgeEvents | null>(null);
  const [bridgeDiag, setBridgeDiag] = useState<AgentOpsCursorBridgeDiagnostics | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [s, r, f, a, sm, d, b, bd] = await Promise.all([
        getAgentStatus(),
        getAgentOpsRecovery(15),
        getAgentOpsFailedInvestigations(15),
        getAgentOpsActiveTasks(),
        getAgentOpsSmokeChecks(15),
        getAgentOpsDeployTracker(8),
        getAgentOpsCursorBridgeEvents(15),
        getAgentOpsCursorBridgeDiagnostics(),
      ]);
      setStatus(s);
      setRecovery(r);
      setFailed(f);
      setActive(a);
      setSmoke(sm);
      setDeploy(d);
      setBridge(b);
      setBridgeDiag(bd);
      setLastRefresh(new Date());
    } catch (e) {
      console.warn('Agent Ops fetch error:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchAll]);

  // Build map of task_id -> most recent event timestamp for stale highlighting
  const taskIdToLastEventTs = useMemo(() => {
    const map = new Map<string, number>();
    const add = (taskId: string | null, ts: string) => {
      if (!taskId?.trim()) return;
      try {
        const ms = new Date(ts).getTime();
        if (!isNaN(ms)) {
          const cur = map.get(taskId);
          if (!cur || ms > cur) map.set(taskId, ms);
        }
      } catch {
        /* ignore */
      }
    };
    for (const e of recovery?.recovery_actions ?? []) {
      add(e.task_id ?? null, e.timestamp);
    }
    for (const e of smoke?.smoke_checks ?? []) {
      add(e.task_id ?? null, e.timestamp);
    }
    for (const e of failed?.failed_investigations ?? []) {
      add(e.task_id ?? null, e.timestamp);
    }
    for (const d of deploy?.recent_deploys ?? []) {
      add(d.task_id ?? null, d.triggered_at);
    }
    for (const e of bridge?.cursor_bridge_events ?? []) {
      add(e.task_id ?? null, e.timestamp);
    }
    return map;
  }, [recovery, smoke, failed, deploy, bridge]);

  return (
    <div className={`flex flex-col gap-4 ${embedded ? '' : 'p-4'}`} data-testid={embedded ? 'jarvis-system-status' : 'agent-ops-tab'}>
      {!embedded && (
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Agent Ops</h2>
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {lastRefresh ? `Updated ${formatTs(lastRefresh.toISOString())}` : '—'}
            </span>
            <button
              onClick={fetchAll}
              disabled={loading}
              className="px-3 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              {loading ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
        </div>
      )}
      {embedded && (
        <div className="flex items-center justify-end gap-3">
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {lastRefresh ? `Updated ${formatTs(lastRefresh.toISOString())}` : '—'}
          </span>
          <button
            onClick={fetchAll}
            disabled={loading}
            type="button"
            className="px-3 py-1.5 text-sm font-medium text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-700 rounded hover:bg-indigo-50 dark:hover:bg-indigo-900/30 disabled:opacity-50 transition-colors"
          >
            {loading ? 'Refreshing…' : 'Refresh status'}
          </button>
        </div>
      )}

      {/* API errors when ok is false */}
      {((recovery && !recovery.ok) || (failed && !failed.ok) || (active && !active.ok) || (smoke && !smoke.ok) || (deploy && !deploy.ok) || (bridge && !bridge.ok)) && (
        <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-3 text-sm text-amber-800 dark:text-amber-200">
          Some data may be unavailable. Check backend logs.
        </div>
      )}

      {/* Scheduler state */}
      {status && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Scheduler</h3>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-sm">
            <div>
              <span className="text-gray-500 dark:text-gray-400">Running</span>
              <p className="mt-0.5">
                <StatusBadge variant={status.scheduler_running ? 'success' : 'danger'} title={status.scheduler_running ? 'Scheduler is running' : 'Scheduler is stopped'}>
                  {status.scheduler_running ? 'Running' : 'Stopped'}
                </StatusBadge>
              </p>
            </div>
            <div>
              <span className="text-gray-500 dark:text-gray-400">Automation</span>
              <p className="mt-0.5">
                <StatusBadge variant={status.automation_enabled ? 'success' : 'neutral'} title={status.automation_enabled ? 'Automation enabled' : 'Automation disabled'}>
                  {status.automation_enabled ? 'Enabled' : 'Disabled'}
                </StatusBadge>
              </p>
            </div>
            <div>
              <span className="text-gray-500 dark:text-gray-400">Last cycle</span>
              <p className="font-medium">{status.last_scheduler_cycle || '—'}</p>
            </div>
            <div>
              <span className="text-gray-500 dark:text-gray-400">Interval (s)</span>
              <p className="font-medium">{typeof status.scheduler_interval_s === 'number' ? status.scheduler_interval_s : '—'}</p>
            </div>
            <div>
              <span className="text-gray-500 dark:text-gray-400">Pending approvals</span>
              <p className="font-medium">{status.pending_approvals >= 0 ? status.pending_approvals : '—'}</p>
            </div>
          </div>
          <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-700 grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs">
            <span>Planned: {status.pending_notion_tasks >= 0 ? status.pending_notion_tasks : '—'}</span>
            <span>Investigation: {status.tasks_in_investigation >= 0 ? status.tasks_in_investigation : '—'}</span>
            <span>Patching: {status.tasks_in_patch_phase >= 0 ? status.tasks_in_patch_phase : '—'}</span>
            <span>Awaiting deploy: {status.tasks_awaiting_deploy >= 0 ? status.tasks_awaiting_deploy : '—'}</span>
            <span>Deploying: {status.tasks_deploying >= 0 ? status.tasks_deploying : '—'}</span>
          </div>
        </div>
      )}

      {/* Active tasks */}
      {active && active.ok && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <TaskTable
            title="Patching"
            tasks={active.patching}
            badgeVariant="warning"
            taskIdToLastEventTs={taskIdToLastEventTs}
            staleThresholdMs={STALE_THRESHOLD_MS}
          />
          <TaskTable
            title="Deploying"
            tasks={active.deploying}
            badgeVariant="success"
            taskIdToLastEventTs={taskIdToLastEventTs}
            staleThresholdMs={STALE_DEPLOYING_MS}
          />
          <TaskTable
            title="Awaiting deploy approval"
            tasks={active.awaiting_deploy_approval}
            badgeVariant="neutral"
            taskIdToLastEventTs={taskIdToLastEventTs}
            staleThresholdMs={STALE_THRESHOLD_MS}
          />
        </div>
      )}

      {/* Recovery, smoke checks, failed, deploys */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <EventList
          title="Recent recovery actions"
          items={recovery?.recovery_actions ?? []}
          emptyMsg="No recovery actions"
          renderItem={(item) => {
            const outcome = item.details?.outcome ? String(item.details.outcome) : null;
            const passed = outcome === 'passed' || outcome === 'regenerated' || outcome === 'advanced';
            return (
              <>
                <span className="text-gray-500 dark:text-gray-400">{formatTs(item.timestamp)}</span>
                <span className="mx-2 font-mono text-xs text-gray-600 dark:text-gray-400">{item.event_type}</span>
                <span className="text-gray-700 dark:text-gray-300">{item.task_title || item.task_id || '—'}</span>
                {outcome && (
                  <span className="ml-2">
                    <StatusBadge variant={passed ? 'success' : 'warning'} title={`Outcome: ${outcome}`}>
                      {outcome}
                    </StatusBadge>
                  </span>
                )}
              </>
            );
          }}
        />
        <EventList
          title="Recent smoke checks"
          items={smoke?.smoke_checks ?? []}
          emptyMsg="No smoke checks"
          renderItem={(item) => {
            const outcome = item.details?.outcome ? String(item.details.outcome) : null;
            const passed = outcome === 'passed';
            return (
              <>
                <span className="text-gray-500 dark:text-gray-400">{formatTs(item.timestamp)}</span>
                <span className="mx-2 font-mono text-xs text-gray-600 dark:text-gray-400">{item.event_type}</span>
                <span className="text-gray-700 dark:text-gray-300">{item.task_title || item.task_id || '—'}</span>
                {outcome && (
                  <span className="ml-2">
                    <StatusBadge variant={passed ? 'success' : 'warning'} title={passed ? 'Smoke check passed' : 'Smoke check failed or pending'}>
                      {outcome}
                    </StatusBadge>
                  </span>
                )}
              </>
            );
          }}
        />
        {bridgeDiag?.ok && (
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
            <h3 className="px-4 py-2 text-sm font-semibold text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
              Cursor bridge readiness
            </h3>
            <div className="p-4 flex flex-wrap gap-3 items-center">
              <StatusBadge
                variant={bridgeDiag.ready ? 'success' : bridgeDiag.enabled ? 'warning' : 'neutral'}
                title={bridgeDiag.ready ? 'Bridge ready to run' : bridgeDiag.enabled ? 'Missing CLI or staging' : 'Bridge disabled'}
              >
                {bridgeDiag.ready ? 'Ready' : bridgeDiag.enabled ? 'Not ready' : 'Disabled'}
              </StatusBadge>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                CLI: {bridgeDiag.cursor_cli_found ? '✓' : '✗'} · Staging: {bridgeDiag.staging_root_writable ? '✓' : '✗'} · Handoffs: {bridgeDiag.handoff_dir_exists ? '✓' : '✗'} · PR: {bridgeDiag.github_token_set ? '✓' : '✗'}
              </span>
            </div>
          </div>
        )}
        <EventList
          title="Cursor bridge events"
          items={bridge?.cursor_bridge_events ?? []}
          emptyMsg="No cursor bridge events"
          renderItem={(item) => {
            const success = /done|success|provisioned|created/.test(item.event_type);
            const failed = /failed|timeout|error/.test(item.event_type);
            return (
              <>
                <span className="text-gray-500 dark:text-gray-400">{formatTs(item.timestamp)}</span>
                <span className="mx-2 font-mono text-xs text-gray-600 dark:text-gray-400">{item.event_type}</span>
                <span className="text-gray-700 dark:text-gray-300">{item.task_title || item.task_id || '—'}</span>
                <span className="ml-2">
                  <StatusBadge variant={success ? 'success' : failed ? 'danger' : 'neutral'} title={item.event_type}>
                    {item.event_type.replace('cursor_bridge_', '')}
                  </StatusBadge>
                </span>
              </>
            );
          }}
        />
        <EventList
          title="Failed investigations"
          items={failed?.failed_investigations ?? []}
          emptyMsg="No failed investigations"
          headerBadge={
            (failed?.failed_investigations?.length ?? 0) > 0 ? (
              <StatusBadge variant="danger">{failed!.failed_investigations!.length} failed</StatusBadge>
            ) : undefined
          }
          renderItem={(item) => (
            <>
              <span className="text-gray-500 dark:text-gray-400">{formatTs(item.timestamp)}</span>
              <span className="mx-2">
                <StatusBadge variant="danger" title={item.event_type}>
                  {item.event_type}
                </StatusBadge>
              </span>
              <span className="text-gray-700 dark:text-gray-300">{item.task_title || item.task_id || '—'}</span>
              {item.details?.summary && (
                <p className="mt-1 text-xs text-gray-500 dark:text-gray-400 truncate max-w-md" title={String(item.details.summary)}>
                  {String(item.details.summary)}
                </p>
              )}
            </>
          )}
        />
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
          <h3 className="px-4 py-2 text-sm font-semibold text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
            Recent deploys
          </h3>
          <div className="max-h-48 overflow-y-auto p-4">
            {deploy?.ok && deploy.recent_deploys.length > 0 ? (
              <ul className="space-y-2 text-sm">
                {deploy.recent_deploys.map((d, i) => (
                  <li key={i} className="flex flex-col gap-0.5">
                    <div className="flex justify-between gap-2">
                      <span className="font-mono text-xs truncate">{d.task_id ?? '—'}</span>
                      <span className="text-gray-500 shrink-0">{formatTs(d.triggered_at)}</span>
                    </div>
                    {d.triggered_by && (
                      <span className="text-xs text-gray-500">by {d.triggered_by}</span>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-gray-500 dark:text-gray-400">No recent deploys</p>
            )}
            {deploy?.ok && deploy.last_deploy_task_id && (
              <p className="mt-2 pt-2 border-t border-gray-200 dark:border-gray-700 text-xs text-gray-500">
                Last deploy task: <code className="font-mono">{deploy.last_deploy_task_id}</code>
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
