'use client';

import React, { useCallback, useEffect, useState } from 'react';
import AgentOpsTab from '@/app/components/tabs/AgentOpsTab';
import {
  getJarvisTaskDetail,
  getJarvisTaskList,
  postJarvisAdvisorTask,
  type JarvisRiskLevel,
  type JarvisTaskResponse,
  type JarvisTaskRunDetail,
  type JarvisTaskRunSummary,
} from '@/app/api';

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

function formatTs(ts: string | null | undefined): string {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    return isNaN(d.getTime()) ? ts : d.toLocaleString();
  } catch {
    return ts;
  }
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

export default function JarvisTab() {
  const [prompt, setPrompt] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [lastResponse, setLastResponse] = useState<JarvisTaskResponse | null>(null);
  const [history, setHistory] = useState<JarvisTaskRunSummary[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<JarvisTaskRunDetail | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [systemStatusOpen, setSystemStatusOpen] = useState(false);

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
  }, [loadHistory]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = prompt.trim();
    if (!text || submitting) return;

    setSubmitting(true);
    setSubmitError(null);
    setSelectedTaskId(null);
    setSelectedDetail(null);

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

  const handleSelectHistory = async (taskId: string) => {
    setSelectedTaskId(taskId);
    setSelectedDetail(null);
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
          <span
            className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-900/40 dark:text-blue-200 dark:border-blue-700"
            data-testid="jarvis-mode-advisor"
          >
            Advisor Mode
          </span>
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
        </div>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          Ask Jarvis read-only questions powered by AWS Bedrock. Responses are advisory only — no writes, deploys, or
          trading actions are available from this tab.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-3" data-testid="jarvis-advisor-form">
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

      {submitError && (
        <div
          className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 p-3 text-sm text-red-800 dark:text-red-200"
          data-testid="jarvis-submit-error"
        >
          {submitError}
        </div>
      )}

      {displayDetail && (
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
