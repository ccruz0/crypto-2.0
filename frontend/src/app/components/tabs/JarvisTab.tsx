'use client';

import React, { useCallback, useEffect, useState } from 'react';
import AgentOpsTab from '@/app/components/tabs/AgentOpsTab';
import {
  getJarvisBuilderTask,
  getJarvisControlStatus,
  getJarvisTaskDetail,
  getJarvisTaskList,
  postJarvisAdvisorTask,
  postJarvisBuilderPrepare,
  type JarvisBuilderPrepareResponse,
  type JarvisControlStatus,
  type JarvisRiskLevel,
  type JarvisTaskResponse,
  type JarvisTaskRunDetail,
  type JarvisTaskRunSummary,
} from '@/app/api';

type JarvisMode = 'advisor' | 'builder';

function RiskBadge({ level }: { level: JarvisRiskLevel | string }) {
  const normalized = (level || 'low').toLowerCase();
  const variant =
    normalized === 'high'
      ? 'bg-red-100 text-red-800 border-red-200 dark:bg-red-900/40 dark:text-red-200 dark:border-red-700'
      : normalized === 'medium'
        ? 'bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-900/40 dark:text-amber-200 dark:border-amber-700'
        : 'bg-green-100 text-green-800 border-green-200 dark:bg-green-900/40 dark:text-green-200 dark:border-green-700';
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border ${variant}`}>
      Risk: {normalized}
    </span>
  );
}

function StubBadge() {
  return (
    <span
      className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border bg-purple-100 text-purple-800 border-purple-200 dark:bg-purple-900/40 dark:text-purple-200 dark:border-purple-700"
      data-testid="jarvis-stub-badge"
    >
      Stub
    </span>
  );
}

function formatTs(ts: string | null | undefined): string {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    return isNaN(d.getTime()) ? ts : d.toLocaleString();
  } catch {
    return ts;
  }
}

function formatBool(value: boolean): string {
  return value ? 'Yes' : 'No';
}

function AuditTrailSection({ detail }: { detail: JarvisTaskResponse | JarvisTaskRunDetail }) {
  const plan = detail.plan ?? [];
  const toolResults = detail.tool_results ?? [];
  const review = detail.review ?? {};

  return (
    <div className="space-y-3" data-testid="jarvis-audit-trail">
      <div className="text-xs text-gray-500 dark:text-gray-400 font-mono">
        Task ID: {detail.task_id}
        {'status' in detail && detail.status ? ` · Status: ${detail.status}` : ''}
        {'estimated_cost_usd' in detail && typeof detail.estimated_cost_usd === 'number'
          ? ` · Est. cost: $${detail.estimated_cost_usd.toFixed(4)}`
          : ''}
      </div>

      {plan.length > 0 && (
        <details className="rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300">
            Plan ({plan.length} step{plan.length === 1 ? '' : 's'})
          </summary>
          <pre className="px-3 pb-3 text-xs overflow-x-auto text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
            {JSON.stringify(plan, null, 2)}
          </pre>
        </details>
      )}

      {toolResults.length > 0 && (
        <details className="rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300">
            Tool results ({toolResults.length})
          </summary>
          <pre className="px-3 pb-3 text-xs overflow-x-auto text-gray-700 dark:text-gray-300 whitespace-pre-wrap max-h-64 overflow-y-auto">
            {JSON.stringify(toolResults, null, 2)}
          </pre>
        </details>
      )}

      {Object.keys(review).length > 0 && (
        <details className="rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300">
            Review
          </summary>
          <pre className="px-3 pb-3 text-xs overflow-x-auto text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
            {JSON.stringify(review, null, 2)}
          </pre>
        </details>
      )}

      {'error' in detail && detail.error && (
        <p className="text-sm text-red-600 dark:text-red-400" data-testid="jarvis-error">
          {detail.error}
        </p>
      )}
    </div>
  );
}

function BuilderStatusPanel({ status }: { status: JarvisControlStatus }) {
  return (
    <div
      className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-4 space-y-2"
      data-testid="jarvis-builder-status-panel"
    >
      <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200">Builder environment</h3>
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
        <div>
          <dt className="text-gray-500 dark:text-gray-400">Environment</dt>
          <dd className="font-medium text-gray-900 dark:text-gray-100" data-testid="jarvis-builder-env">
            {status.environment}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500 dark:text-gray-400">Trading-only</dt>
          <dd className="font-medium text-gray-900 dark:text-gray-100" data-testid="jarvis-builder-trading-only">
            {formatBool(status.trading_only)}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500 dark:text-gray-400">Control enabled</dt>
          <dd className="font-medium text-gray-900 dark:text-gray-100">{formatBool(status.control_enabled)}</dd>
        </div>
        <div>
          <dt className="text-gray-500 dark:text-gray-400">Builder allowed</dt>
          <dd className="font-medium text-gray-900 dark:text-gray-100">{formatBool(status.builder_allowed)}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-gray-500 dark:text-gray-400">Builder available</dt>
          <dd className="font-medium text-gray-900 dark:text-gray-100" data-testid="jarvis-builder-available">
            {formatBool(status.builder_available)}
          </dd>
        </div>
      </dl>
    </div>
  );
}

function builderUnavailableReason(status: JarvisControlStatus | null): string | null {
  if (!status || status.builder_available) return null;
  if (status.trading_only) {
    return 'Trading-only mode is enabled on this host (ATP_TRADING_ONLY=1).';
  }
  if (!status.builder_allowed) {
    return 'Builder is not allowed on this host (JARVIS_BUILDER_ALLOWED is off).';
  }
  if (!status.control_enabled) {
    return 'Jarvis Control Center is disabled (JARVIS_CONTROL_ENABLED is off).';
  }
  return 'Builder gates are not open on this environment.';
}

export default function JarvisTab() {
  const [mode, setMode] = useState<JarvisMode>('advisor');
  const [prompt, setPrompt] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [lastResponse, setLastResponse] = useState<JarvisTaskResponse | null>(null);
  const [builderResponse, setBuilderResponse] = useState<JarvisBuilderPrepareResponse | null>(null);
  const [history, setHistory] = useState<JarvisTaskRunSummary[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<JarvisTaskRunDetail | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [systemStatusOpen, setSystemStatusOpen] = useState(false);
  const [controlStatus, setControlStatus] = useState<JarvisControlStatus | null>(null);
  const [controlStatusLoading, setControlStatusLoading] = useState(true);
  const [controlStatusError, setControlStatusError] = useState<string | null>(null);

  const controlApiAvailable = controlStatus !== null;
  const builderAvailable = controlStatus?.builder_available === true;
  const builderUnavailableMessage = builderUnavailableReason(controlStatus);

  const loadControlStatus = useCallback(async () => {
    setControlStatusLoading(true);
    setControlStatusError(null);
    try {
      const status = await getJarvisControlStatus();
      setControlStatus(status);
    } catch (e) {
      setControlStatus(null);
      setControlStatusError(e instanceof Error ? e.message : String(e));
    } finally {
      setControlStatusLoading(false);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const res = await getJarvisTaskList(15);
      setHistory(res.tasks ?? []);
    } catch (e) {
      console.warn('Jarvis task history fetch failed:', e);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHistory();
    loadControlStatus();
  }, [loadHistory, loadControlStatus]);

  const handleAdvisorSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = prompt.trim();
    if (!text || submitting) return;

    setSubmitting(true);
    setSubmitError(null);
    setSelectedTaskId(null);
    setSelectedDetail(null);
    setBuilderResponse(null);

    try {
      const res = await postJarvisAdvisorTask(text);
      setLastResponse(res);
      await loadHistory();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
      setLastResponse(null);
    } finally {
      setSubmitting(false);
    }
  };

  const handleBuilderSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = prompt.trim();
    if (!text || submitting || !builderAvailable) return;

    setSubmitting(true);
    setSubmitError(null);
    setLastResponse(null);
    setSelectedTaskId(null);
    setSelectedDetail(null);
    setBuilderResponse(null);

    try {
      const res = await postJarvisBuilderPrepare(text, { requested_by: 'dashboard' });
      setBuilderResponse(res);
      try {
        await getJarvisBuilderTask(res.task_id);
      } catch (detailErr) {
        console.warn('Jarvis builder task detail fetch failed:', detailErr);
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
      setBuilderResponse(null);
    } finally {
      setSubmitting(false);
    }
  };

  const handleSelectHistory = async (taskId: string) => {
    setSelectedTaskId(taskId);
    setSelectedDetail(null);
    setBuilderResponse(null);
    try {
      const detail = await getJarvisTaskDetail(taskId);
      setSelectedDetail(detail);
    } catch (e) {
      console.warn('Jarvis task detail fetch failed:', e);
    }
  };

  const displayDetail = selectedDetail ?? lastResponse;

  return (
    <div className="flex flex-col gap-6 p-4" data-testid="jarvis-tab">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Jarvis Control Center</h2>
          <div className="inline-flex rounded-lg border border-gray-200 dark:border-gray-600 overflow-hidden" data-testid="jarvis-mode-selector">
            <button
              type="button"
              onClick={() => setMode('advisor')}
              className={`px-3 py-1.5 text-xs font-semibold transition-colors ${
                mode === 'advisor'
                  ? 'bg-blue-600 text-white'
                  : 'bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800'
              }`}
              data-testid="jarvis-mode-advisor"
            >
              Advisor
            </button>
            {controlApiAvailable && (
              <button
                type="button"
                onClick={() => setMode('builder')}
                className={`px-3 py-1.5 text-xs font-semibold transition-colors border-l border-gray-200 dark:border-gray-600 ${
                  mode === 'builder'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800'
                }`}
                data-testid="jarvis-mode-builder"
              >
                Builder
              </button>
            )}
          </div>
          {mode === 'advisor' && (
            <>
              <span
                className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-700/40 dark:text-gray-300 dark:border-gray-600"
                data-testid="jarvis-mode-readonly"
              >
                Read-only
              </span>
              <span
                className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-900/40 dark:text-amber-200 dark:border-amber-700"
                data-testid="jarvis-no-prod-changes"
              >
                No production changes allowed
              </span>
            </>
          )}
          {mode === 'builder' && builderAvailable && (
            <StubBadge />
          )}
        </div>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          {mode === 'advisor'
            ? 'Ask Jarvis read-only questions powered by AWS Bedrock. Responses are advisory only — no writes, deploys, or trading actions are available from this tab.'
            : 'Prepare Builder tasks in stub mode. Tasks are persisted for review — no Cursor bridge, governance, PR, or execution occurs in this phase.'}
        </p>
      </div>

      {mode === 'builder' && controlStatus && <BuilderStatusPanel status={controlStatus} />}

      {mode === 'builder' && controlStatusLoading && (
        <p className="text-sm text-gray-500 dark:text-gray-400">Loading Builder status…</p>
      )}

      {mode === 'builder' && controlStatusError && (
        <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-3 text-sm text-amber-900 dark:text-amber-100">
          Control status unavailable: {controlStatusError}
        </div>
      )}

      {mode === 'builder' && !builderAvailable && controlStatus && (
        <div
          className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-3 text-sm text-amber-900 dark:text-amber-100"
          data-testid="jarvis-builder-unavailable"
        >
          <p className="font-medium">Builder Mode unavailable in this environment.</p>
          {builderUnavailableMessage && <p className="mt-1 text-amber-800 dark:text-amber-200">{builderUnavailableMessage}</p>}
        </div>
      )}

      {mode === 'advisor' ? (
        <form onSubmit={handleAdvisorSubmit} className="space-y-3" data-testid="jarvis-advisor-form">
          <label htmlFor="jarvis-prompt" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
            Ask Jarvis
          </label>
          <textarea
            id="jarvis-prompt"
            data-testid="jarvis-prompt-input"
            rows={4}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g. Summarize AWS cost optimization opportunities, or explain the current trading scheduler health…"
            className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            disabled={submitting}
          />
          <div className="flex items-center gap-3">
            <button
              type="submit"
              data-testid="jarvis-submit-button"
              disabled={submitting || !prompt.trim()}
              className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              {submitting ? 'Thinking…' : 'Ask (read-only)'}
            </button>
            <span className="text-xs text-gray-500 dark:text-gray-400">Always runs with dry_run=true</span>
          </div>
        </form>
      ) : (
        <form onSubmit={handleBuilderSubmit} className="space-y-3" data-testid="jarvis-builder-form">
          <label htmlFor="jarvis-builder-prompt" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
            Builder prompt
          </label>
          <textarea
            id="jarvis-builder-prompt"
            data-testid="jarvis-builder-prompt-input"
            rows={4}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g. Add structured logging to the backend health endpoint…"
            className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            disabled={submitting || !builderAvailable}
          />
          <div className="flex items-center gap-3">
            <button
              type="submit"
              data-testid="jarvis-builder-submit-button"
              disabled={submitting || !prompt.trim() || !builderAvailable}
              className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              {submitting ? 'Preparing…' : 'Prepare (stub)'}
            </button>
            <span className="text-xs text-gray-500 dark:text-gray-400">Creates a queued stub task only</span>
          </div>
        </form>
      )}

      {submitError && (
        <div
          className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 p-3 text-sm text-red-800 dark:text-red-200"
          data-testid="jarvis-submit-error"
        >
          {submitError}
        </div>
      )}

      {mode === 'advisor' && displayDetail && (
        <div
          className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 space-y-4"
          data-testid="jarvis-response-panel"
        >
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200">Response</h3>
            <RiskBadge level={displayDetail.risk_level} />
            {'dry_run' in displayDetail && displayDetail.dry_run !== false && (
              <span className="text-xs text-gray-500 dark:text-gray-400">(dry run)</span>
            )}
          </div>
          <div
            className="text-sm text-gray-800 dark:text-gray-200 whitespace-pre-wrap"
            data-testid="jarvis-final-answer"
          >
            {displayDetail.final_answer || '(No answer text returned)'}
          </div>
          <AuditTrailSection detail={displayDetail} />
        </div>
      )}

      {mode === 'builder' && builderResponse && (
        <div
          className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 space-y-3"
          data-testid="jarvis-builder-response-panel"
        >
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200">Builder prepare response</h3>
            <RiskBadge level={builderResponse.risk_level} />
            {builderResponse.stub && <StubBadge />}
          </div>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-gray-500 dark:text-gray-400">Task ID</dt>
              <dd className="font-mono text-gray-900 dark:text-gray-100" data-testid="jarvis-builder-task-id">
                {builderResponse.task_id}
              </dd>
            </div>
            <div>
              <dt className="text-gray-500 dark:text-gray-400">Status</dt>
              <dd className="font-medium text-gray-900 dark:text-gray-100" data-testid="jarvis-builder-task-status">
                {builderResponse.status}
              </dd>
            </div>
          </dl>
          <p className="text-sm text-gray-700 dark:text-gray-300" data-testid="jarvis-builder-message">
            {builderResponse.message}
          </p>
        </div>
      )}

      {mode === 'advisor' && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
          <h3 className="px-4 py-2 text-sm font-semibold text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
            Recent Jarvis tasks
          </h3>
          <div className="max-h-48 overflow-y-auto">
            {historyLoading ? (
              <p className="px-4 py-3 text-sm text-gray-500">Loading…</p>
            ) : history.length === 0 ? (
              <p className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">No prior tasks yet</p>
            ) : (
              <ul className="divide-y divide-gray-200 dark:divide-gray-700">
                {history.map((t) => (
                  <li key={t.task_id}>
                    <button
                      type="button"
                      onClick={() => handleSelectHistory(t.task_id)}
                      className={`w-full text-left px-4 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-800/80 transition-colors ${
                        selectedTaskId === t.task_id ? 'bg-indigo-50 dark:bg-indigo-900/20' : ''
                      }`}
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-gray-800 dark:text-gray-200 truncate max-w-xl">{t.task}</span>
                        <RiskBadge level={t.risk_level} />
                      </div>
                      <span className="text-xs text-gray-500">{formatTs(t.created_at)} · {t.status}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      <section className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
        <button
          type="button"
          onClick={() => setSystemStatusOpen((o) => !o)}
          className="w-full flex items-center justify-between px-4 py-3 text-left bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 hover:bg-gray-100 dark:hover:bg-gray-750 transition-colors"
          data-testid="jarvis-system-status-toggle"
        >
          <span className="text-sm font-semibold text-gray-700 dark:text-gray-300">System Status</span>
          <span className="text-xs text-gray-500 dark:text-gray-400">{systemStatusOpen ? 'Hide' : 'Show'} agent telemetry</span>
        </button>
        {systemStatusOpen && (
          <div className="p-4 border-t border-gray-200 dark:border-gray-700">
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
              Read-only scheduler, deploy, and bridge telemetry (legacy Agent Ops). May be unavailable when
              ATP_TRADING_ONLY=1.
            </p>
            <AgentOpsTab embedded />
          </div>
        )}
      </section>
    </div>
  );
}
