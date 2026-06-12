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
  getJarvisControlStatus,
  probeAgentApiAvailable,
  type AgentStatus,
  type AgentOpsRecovery,
  type AgentOpsFailedInvestigations,
  type AgentOpsActiveTasks,
  type AgentOpsSmokeChecks,
  type AgentOpsDeployTracker,
  type AgentOpsCursorBridgeEvents,
  type AgentOpsCursorBridgeDiagnostics,
  type JarvisControlStatus,
} from '@/app/api';

const POLL_INTERVAL_MS = 45000;
const STALE_THRESHOLD_MS = 15 * 60 * 1000;
const STALE_DEPLOYING_MS = 10 * 60 * 1000;

function StatusBadge({
  variant,
  children,
  title,
}: {
  variant: 'success' | 'danger' | 'warning' | 'neutral' | 'info';
  children: React.ReactNode;
  title?: string;
}) {
  const classes = {
    success: 'bg-green-100 text-green-800 border-green-200 dark:bg-green-900/40 dark:text-green-200 dark:border-green-700',
    danger: 'bg-red-100 text-red-800 border-red-200 dark:bg-red-900/40 dark:text-red-200 dark:border-red-700',
    warning: 'bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-900/40 dark:text-amber-200 dark:border-amber-700',
    neutral: 'bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-700/40 dark:text-gray-300 dark:border-gray-600',
    info: 'bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-900/40 dark:text-blue-200 dark:border-blue-700',
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

export default function JarvisControlTab() {
  const [prompt, setPrompt] = useState('');
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);
  const [controlStatus, setControlStatus] = useState<JarvisControlStatus | null>(null);
  const [agentApiAvailable, setAgentApiAvailable] = useState(false);
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

  const tradingOnly = controlStatus?.trading_only ?? !agentApiAvailable;
  const automationEnabled = controlStatus?.available
    ? Boolean(controlStatus.control_enabled)
    : agentApiAvailable && Boolean(status?.automation_enabled);
  const builderAllowed = Boolean(controlStatus?.builder_allowed && controlStatus?.builder_available);
  const schedulerRunning = agentApiAvailable && Boolean(status?.scheduler_running);
  const pendingApprovals = agentApiAvailable && typeof status?.pending_approvals === 'number' && status.pending_approvals >= 0
    ? status.pending_approvals
    : null;

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [jarvisStatus, agentAvailable] = await Promise.all([
        getJarvisControlStatus(),
        probeAgentApiAvailable(),
      ]);
      setControlStatus(jarvisStatus);
      setAgentApiAvailable(agentAvailable);

      if (agentAvailable) {
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
      } else {
        setStatus(null);
        setRecovery(null);
        setFailed(null);
        setActive(null);
        setSmoke(null);
        setDeploy(null);
        setBridge(null);
        setBridgeDiag(null);
      }
      setLastRefresh(new Date());
    } catch (e) {
      console.warn('Jarvis Control Center fetch error:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchAll]);

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

  const handleSubmit = () => {
    const trimmed = prompt.trim();
    if (!trimmed) return;

    if (controlStatus?.error === 'network') {
      setSubmitMessage('Unable to reach Jarvis status API. Your request was not executed.');
      return;
    }

    if (!controlStatus?.available || tradingOnly || !builderAllowed) {
      setSubmitMessage('Jarvis automation is currently disabled in production. Your request was not executed.');
      return;
    }

    setSubmitMessage('Jarvis received your request. Execution is not enabled in this environment yet.');
  };

  const statusBannerMessage = useMemo(() => {
    if (controlStatus?.error === 'network') {
      return 'Unable to reach Jarvis status API. Automation status may be incomplete.';
    }
    if (tradingOnly) {
      return 'Production is in safe trading-only mode. Jarvis automation and builder execution are disabled; trading continues normally.';
    }
    if (controlStatus?.available && !controlStatus.control_enabled) {
      return 'Jarvis Control Center API is reachable but control is disabled on this host.';
    }
    return null;
  }, [controlStatus, tradingOnly]);

  const hasRealAgentErrors = agentApiAvailable && (
    (recovery && !recovery.ok && recovery.error) ||
    (failed && !failed.ok && failed.error) ||
    (active && !active.ok && active.error) ||
    (smoke && !smoke.ok && smoke.error) ||
    (deploy && !deploy.ok && deploy.error) ||
    (bridge && !bridge.ok && bridge.error)
  );

  return (
    <div className="flex flex-col gap-4 p-4" data-testid="jarvis-tab">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Jarvis Control Center</h2>
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

      <div className="rounded-lg border border-indigo-200 dark:border-indigo-800 bg-white dark:bg-gray-900 p-4 shadow-sm">
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
          {tradingOnly
            ? 'Production is in safe trading-only mode. You can draft tasks here; they will not be executed automatically.'
            : 'Ask Jarvis to investigate, plan, or prepare a task. High-risk actions require approval.'}
        </p>
        <label htmlFor="jarvis-prompt-input" className="sr-only">
          Jarvis task prompt
        </label>
        <textarea
          id="jarvis-prompt-input"
          data-testid="jarvis-prompt-input"
          value={prompt}
          onChange={(e) => {
            setPrompt(e.target.value);
            if (submitMessage) setSubmitMessage(null);
          }}
          rows={4}
          placeholder="Ask Jarvis to investigate, plan, or prepare a task…"
          className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            data-testid="jarvis-submit-button"
            onClick={handleSubmit}
            disabled={!prompt.trim()}
            className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Submit to Jarvis
          </button>
          {submitMessage && (
            <p
              data-testid="jarvis-submit-message"
              className="text-sm text-gray-700 dark:text-gray-300"
              role="status"
            >
              {submitMessage}
            </p>
          )}
        </div>
      </div>

      <div
        className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4"
        data-testid="jarvis-system-status-toggle"
      >
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">System status</h3>
        {statusBannerMessage && (
          <p className="mb-3 text-sm text-blue-800 dark:text-blue-200 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-md px-3 py-2">
            {statusBannerMessage}
          </p>
        )}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 text-sm">
          <div>
            <span className="text-gray-500 dark:text-gray-400">Trading-only mode</span>
            <p className="mt-0.5">
              <StatusBadge variant={tradingOnly ? 'info' : 'success'} title={tradingOnly ? 'Automation gated off for trading safety' : 'Full automation host'}>
                {tradingOnly ? 'Active' : 'Off'}
              </StatusBadge>
            </p>
          </div>
          <div>
            <span className="text-gray-500 dark:text-gray-400">Automation</span>
            <p className="mt-0.5">
              <StatusBadge variant={automationEnabled ? 'success' : 'neutral'} title={automationEnabled ? 'Automation enabled' : 'Automation disabled'}>
                {automationEnabled ? 'Enabled' : 'Disabled'}
              </StatusBadge>
            </p>
          </div>
          <div>
            <span className="text-gray-500 dark:text-gray-400">Builder</span>
            <p className="mt-0.5">
              <StatusBadge variant={builderAllowed ? 'success' : 'neutral'} title={builderAllowed ? 'Builder allowed' : 'Builder not allowed'}>
                {builderAllowed ? 'Allowed' : 'Not allowed'}
              </StatusBadge>
            </p>
          </div>
          <div>
            <span className="text-gray-500 dark:text-gray-400">Scheduler</span>
            <p className="mt-0.5">
              <StatusBadge variant={schedulerRunning ? 'success' : 'neutral'} title={schedulerRunning ? 'Scheduler running' : 'Scheduler stopped'}>
                {schedulerRunning ? 'Running' : 'Stopped'}
              </StatusBadge>
            </p>
          </div>
          <div>
            <span className="text-gray-500 dark:text-gray-400">Pending approvals</span>
            <p className="mt-0.5 font-medium text-gray-900 dark:text-gray-100">
              {pendingApprovals ?? '—'}
            </p>
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Operational Status</h3>

        {hasRealAgentErrors && (
          <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-3 text-sm text-amber-800 dark:text-amber-200 mb-4">
            Some operational metrics failed to load. Try refreshing or check backend logs.
          </div>
        )}

        {!agentApiAvailable && (
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
            Agent orchestration APIs are not mounted on this host (expected in trading-only production).
          </p>
        )}

        {status && agentApiAvailable && (
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 mb-4">
            <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Scheduler details</h4>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-sm">
              <div>
                <span className="text-gray-500 dark:text-gray-400">Last cycle</span>
                <p className="font-medium">{status.last_scheduler_cycle || '—'}</p>
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">Interval (s)</span>
                <p className="font-medium">{typeof status.scheduler_interval_s === 'number' ? status.scheduler_interval_s : '—'}</p>
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">Planned</span>
                <p className="font-medium">{status.pending_notion_tasks >= 0 ? status.pending_notion_tasks : '—'}</p>
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">Investigation</span>
                <p className="font-medium">{status.tasks_in_investigation >= 0 ? status.tasks_in_investigation : '—'}</p>
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">Deploying</span>
                <p className="font-medium">{status.tasks_deploying >= 0 ? status.tasks_deploying : '—'}</p>
              </div>
            </div>
          </div>
        )}

        {active && active.ok && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
            <TaskTable title="Patching" tasks={active.patching} badgeVariant="warning" taskIdToLastEventTs={taskIdToLastEventTs} staleThresholdMs={STALE_THRESHOLD_MS} />
            <TaskTable title="Deploying" tasks={active.deploying} badgeVariant="success" taskIdToLastEventTs={taskIdToLastEventTs} staleThresholdMs={STALE_DEPLOYING_MS} />
            <TaskTable title="Awaiting deploy approval" tasks={active.awaiting_deploy_approval} badgeVariant="neutral" taskIdToLastEventTs={taskIdToLastEventTs} staleThresholdMs={STALE_THRESHOLD_MS} />
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <EventList title="Recent recovery actions" items={recovery?.recovery_actions ?? []} emptyMsg="No recovery actions" renderItem={(item) => {
            const outcome = item.details?.outcome ? String(item.details.outcome) : null;
            const passed = outcome === 'passed' || outcome === 'regenerated' || outcome === 'advanced';
            return (
              <>
                <span className="text-gray-500 dark:text-gray-400">{formatTs(item.timestamp)}</span>
                <span className="mx-2 font-mono text-xs text-gray-600 dark:text-gray-400">{item.event_type}</span>
                <span className="text-gray-700 dark:text-gray-300">{item.task_title || item.task_id || '—'}</span>
                {outcome && <span className="ml-2"><StatusBadge variant={passed ? 'success' : 'warning'} title={`Outcome: ${outcome}`}>{outcome}</StatusBadge></span>}
              </>
            );
          }} />
          <EventList title="Recent smoke checks" items={smoke?.smoke_checks ?? []} emptyMsg="No smoke checks" renderItem={(item) => {
            const outcome = item.details?.outcome ? String(item.details.outcome) : null;
            const passed = outcome === 'passed';
            return (
              <>
                <span className="text-gray-500 dark:text-gray-400">{formatTs(item.timestamp)}</span>
                <span className="mx-2 font-mono text-xs text-gray-600 dark:text-gray-400">{item.event_type}</span>
                <span className="text-gray-700 dark:text-gray-300">{item.task_title || item.task_id || '—'}</span>
                {outcome && <span className="ml-2"><StatusBadge variant={passed ? 'success' : 'warning'} title={passed ? 'Smoke check passed' : 'Smoke check failed or pending'}>{outcome}</StatusBadge></span>}
              </>
            );
          }} />
          {bridgeDiag?.ok && (
            <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
              <h3 className="px-4 py-2 text-sm font-semibold text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Cursor bridge readiness</h3>
              <div className="p-4 flex flex-wrap gap-3 items-center">
                <StatusBadge variant={bridgeDiag.ready ? 'success' : bridgeDiag.enabled ? 'warning' : 'neutral'} title={bridgeDiag.ready ? 'Bridge ready to run' : bridgeDiag.enabled ? 'Missing CLI or staging' : 'Bridge disabled'}>
                  {bridgeDiag.ready ? 'Ready' : bridgeDiag.enabled ? 'Not ready' : 'Disabled'}
                </StatusBadge>
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  CLI: {bridgeDiag.cursor_cli_found ? '✓' : '✗'} · Staging: {bridgeDiag.staging_root_writable ? '✓' : '✗'} · Handoffs: {bridgeDiag.handoff_dir_exists ? '✓' : '✗'} · PR: {bridgeDiag.github_token_set ? '✓' : '✗'}
                </span>
              </div>
            </div>
          )}
          <EventList title="Cursor bridge events" items={bridge?.cursor_bridge_events ?? []} emptyMsg="No cursor bridge events" renderItem={(item) => {
            const success = /done|success|provisioned|created/.test(item.event_type);
            const failed = /failed|timeout|error/.test(item.event_type);
            return (
              <>
                <span className="text-gray-500 dark:text-gray-400">{formatTs(item.timestamp)}</span>
                <span className="mx-2 font-mono text-xs text-gray-600 dark:text-gray-400">{item.event_type}</span>
                <span className="text-gray-700 dark:text-gray-300">{item.task_title || item.task_id || '—'}</span>
                <span className="ml-2"><StatusBadge variant={success ? 'success' : failed ? 'danger' : 'neutral'} title={item.event_type}>{item.event_type.replace('cursor_bridge_', '')}</StatusBadge></span>
              </>
            );
          }} />
          <EventList title="Failed investigations" items={failed?.failed_investigations ?? []} emptyMsg="No failed investigations" headerBadge={(failed?.failed_investigations?.length ?? 0) > 0 ? <StatusBadge variant="danger">{failed!.failed_investigations!.length} failed</StatusBadge> : undefined} renderItem={(item) => (
            <>
              <span className="text-gray-500 dark:text-gray-400">{formatTs(item.timestamp)}</span>
              <span className="mx-2"><StatusBadge variant="danger" title={item.event_type}>{item.event_type}</StatusBadge></span>
              <span className="text-gray-700 dark:text-gray-300">{item.task_title || item.task_id || '—'}</span>
              {item.details?.summary && <p className="mt-1 text-xs text-gray-500 dark:text-gray-400 truncate max-w-md" title={String(item.details.summary)}>{String(item.details.summary)}</p>}
            </>
          )} />
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
            <h3 className="px-4 py-2 text-sm font-semibold text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Recent deploys</h3>
            <div className="max-h-48 overflow-y-auto p-4">
              {deploy?.ok && deploy.recent_deploys.length > 0 ? (
                <ul className="space-y-2 text-sm">
                  {deploy.recent_deploys.map((d, i) => (
                    <li key={i} className="flex flex-col gap-0.5">
                      <div className="flex justify-between gap-2">
                        <span className="font-mono text-xs truncate">{d.task_id ?? '—'}</span>
                        <span className="text-gray-500 shrink-0">{formatTs(d.triggered_at)}</span>
                      </div>
                      {d.triggered_by && <span className="text-xs text-gray-500">by {d.triggered_by}</span>}
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
    </div>
  );
}
