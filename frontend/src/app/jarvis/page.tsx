'use client';

import { useCallback, useEffect, useState } from 'react';
import Badge from '@/components/ui/Badge';
import Table from '@/components/ui/Table';
import {
  getJarvisTask,
  JarvisRiskLevel,
  JarvisTaskRunDetail,
  JarvisTaskRunSummary,
  listJarvisTasks,
  submitJarvisTask,
} from '@/lib/api';

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function truncate(text: string, max = 80): string {
  const t = (text || '').trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max)}…`;
}

function statusBadgeVariant(
  status: string,
  riskLevel: JarvisRiskLevel,
): 'success' | 'danger' | 'warning' | 'neutral' {
  if (status === 'completed') return 'success';
  if (status === 'failed') return 'danger';
  if (status === 'requires_approval' || riskLevel === 'high') return 'danger';
  if (riskLevel === 'medium') return 'warning';
  return 'neutral';
}

function rowClassName(status: string, riskLevel: JarvisRiskLevel): string {
  if (status === 'failed') {
    return 'bg-red-50 dark:bg-red-950/30';
  }
  if (status === 'requires_approval' || riskLevel === 'high') {
    return 'bg-orange-50 dark:bg-orange-950/20';
  }
  if (riskLevel === 'medium') {
    return 'bg-amber-50 dark:bg-amber-950/20';
  }
  if (status === 'completed') {
    return 'hover:bg-green-50/60 dark:hover:bg-green-950/20';
  }
  return 'hover:bg-gray-50 dark:hover:bg-slate-800/60';
}

function JsonBlock({ value, expanded = false }: { value: unknown; expanded?: boolean }) {
  const text = JSON.stringify(value, null, 2);
  const isLarge = text.length > 4000;
  return (
    <pre
      className={`text-xs bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded p-3 overflow-x-auto whitespace-pre-wrap break-words ${
        expanded || isLarge ? 'max-h-[32rem]' : 'max-h-64'
      }`}
    >
      {text}
    </pre>
  );
}

function ReconcileSummary({ toolResults }: { toolResults: unknown }) {
  if (!Array.isArray(toolResults)) return null;
  const reconcile = toolResults.find(
    (item) =>
      item &&
      typeof item === 'object' &&
      (item as { tool?: string }).tool === 'reconcile_crypto_wallet_vs_dashboard',
  ) as
    | {
        status?: string;
        crypto_com_total_usd?: number;
        dashboard_total_usd?: number;
        difference_usd?: number;
        difference_pct?: number;
        probable_root_causes?: string[];
        recommended_next_steps?: string[];
      }
    | undefined;
  if (!reconcile) return null;

  const statusVariant =
    reconcile.status === 'pass' ? 'success' : reconcile.status === 'mismatch' ? 'warning' : 'danger';

  return (
    <div className="rounded border border-amber-300 dark:border-amber-700 bg-amber-50/70 dark:bg-amber-950/20 p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold text-gray-900 dark:text-gray-100">Wallet reconciliation</h3>
        <Badge variant={statusVariant}>{reconcile.status || 'unknown'}</Badge>
      </div>
      <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-sm">
        <div>
          <dt className="text-gray-500 dark:text-gray-400">Crypto.com total (USD)</dt>
          <dd className="font-mono tabular-nums">
            {reconcile.crypto_com_total_usd?.toLocaleString(undefined, { minimumFractionDigits: 2 }) ?? '—'}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500 dark:text-gray-400">Dashboard total (USD)</dt>
          <dd className="font-mono tabular-nums">
            {reconcile.dashboard_total_usd?.toLocaleString(undefined, { minimumFractionDigits: 2 }) ?? '—'}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500 dark:text-gray-400">Difference (USD)</dt>
          <dd className="font-mono tabular-nums">
            {reconcile.difference_usd?.toLocaleString(undefined, { minimumFractionDigits: 2 }) ?? '—'}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500 dark:text-gray-400">Difference (%)</dt>
          <dd className="font-mono tabular-nums">{reconcile.difference_pct ?? '—'}%</dd>
        </div>
      </dl>
      {reconcile.probable_root_causes && reconcile.probable_root_causes.length > 0 && (
        <div>
          <dt className="text-gray-500 dark:text-gray-400 mb-1">Probable root causes</dt>
          <ul className="list-disc pl-5 text-sm space-y-1">
            {reconcile.probable_root_causes.map((cause) => (
              <li key={cause}>{cause}</li>
            ))}
          </ul>
        </div>
      )}
      {reconcile.recommended_next_steps && reconcile.recommended_next_steps.length > 0 && (
        <div>
          <dt className="text-gray-500 dark:text-gray-400 mb-1">Recommended next steps</dt>
          <ul className="list-disc pl-5 text-sm space-y-1">
            {reconcile.recommended_next_steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function JarvisPage() {
  const [taskInput, setTaskInput] = useState('');
  const [dryRun] = useState(true);
  const [running, setRunning] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runMessage, setRunMessage] = useState<string | null>(null);
  const [tasks, setTasks] = useState<JarvisTaskRunSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<JarvisTaskRunDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const data = await listJarvisTasks(20);
      setTasks(data.tasks || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load task history');
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const loadDetail = useCallback(async (taskId: string) => {
    setDetailLoading(true);
    setError(null);
    try {
      const data = await getJarvisTask(taskId);
      setDetail(data);
      setSelectedId(taskId);
    } catch (err) {
      setDetail(null);
      setError(err instanceof Error ? err.message : 'Failed to load task detail');
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const handleRunTask = async () => {
    const task = taskInput.trim();
    if (!task) {
      setError('Enter a task description.');
      return;
    }
    setRunning(true);
    setError(null);
    setRunMessage(null);
    try {
      const result = await submitJarvisTask({ task, dry_run: dryRun });
      setRunMessage(
        `Task ${result.task_id.slice(0, 8)}… finished with status "${result.status}" (${result.risk_level} risk).`,
      );
      setTaskInput('');
      await loadHistory();
      await loadDetail(result.task_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to run Jarvis task');
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <div className="container mx-auto p-4 md:p-8 max-w-7xl">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Jarvis Tasks</h1>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              Read-only LangGraph MVP — dry-run enforced on PROD.
            </p>
          </div>
          <div className="flex gap-3">
            <a
              href="/jarvis/executive"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Executive
            </a>
            <a
              href="/jarvis/initiatives"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Initiatives
            </a>
            <a
              href="/jarvis/decisions"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Decisions
            </a>
            <a
              href="/jarvis/executive-reports"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Weekly Reports
            </a>
            <a
              href="/jarvis/crypto-audits"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Crypto Audits
            </a>
            <a
              href="/jarvis/action-plans"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Action Plans
            </a>
            <a
              href="/jarvis/audits"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              AWS Audits
            </a>
            <a
              href="/monitoring"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              ← Monitoring
            </a>
            <button
              type="button"
              onClick={loadHistory}
              disabled={historyLoading || running}
              className="px-4 py-2 text-sm bg-gray-200 dark:bg-slate-700 rounded-md hover:bg-gray-300 dark:hover:bg-slate-600 disabled:opacity-50"
            >
              {historyLoading ? 'Refreshing…' : 'Refresh history'}
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-300 bg-red-50 dark:bg-red-950/30 text-red-800 dark:text-red-200 px-4 py-3 text-sm">
            {error}
          </div>
        )}
        {runMessage && (
          <div className="mb-4 rounded border border-green-300 bg-green-50 dark:bg-green-950/30 text-green-800 dark:text-green-200 px-4 py-3 text-sm">
            {runMessage}
          </div>
        )}

        <section className="mb-8 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4 md:p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Run task</h2>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2" htmlFor="jarvis-task">
            Task description
          </label>
          <textarea
            id="jarvis-task"
            rows={3}
            value={taskInput}
            onChange={(e) => setTaskInput(e.target.value)}
            placeholder="e.g. check dashboard health and runtime status"
            disabled={running}
            className="w-full rounded-md border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-900 text-gray-900 dark:text-gray-100 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <div className="mt-4 flex flex-wrap items-center gap-4">
            <label className="inline-flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
              <input
                type="checkbox"
                checked={dryRun}
                disabled
                readOnly
                className="rounded border-gray-300"
              />
              Dry run (read-only tools only)
            </label>
            <button
              type="button"
              onClick={handleRunTask}
              disabled={running || !taskInput.trim()}
              className="px-5 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-sm font-medium"
            >
              {running ? 'Running…' : 'Run Jarvis Task'}
            </button>
          </div>
          <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
            High-risk tasks (delete, terminate, trade, secrets/IAM) return{' '}
            <code>requires_approval</code> and never execute tools.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Task history</h2>
          {historyLoading && tasks.length === 0 ? (
            <div className="text-center py-8 text-gray-500">Loading history…</div>
          ) : tasks.length === 0 ? (
            <div className="text-center py-8 text-gray-500 border rounded-lg bg-white dark:bg-slate-800">
              No task runs yet. Submit a task above.
            </div>
          ) : (
            <Table className="dark:bg-slate-800 dark:border-slate-700">
              <thead className="bg-gray-50 dark:bg-slate-900 text-left text-xs uppercase text-gray-500 dark:text-gray-400">
                <tr>
                  <th className="px-4 py-3">Created</th>
                  <th className="px-4 py-3">Task</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Risk</th>
                  <th className="px-4 py-3 text-right">Cost (USD)</th>
                  <th className="px-4 py-3">Completed</th>
                  <th className="px-4 py-3">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-slate-700">
                {tasks.map((row) => (
                  <tr
                    key={row.task_id}
                    className={`${rowClassName(row.status, row.risk_level)} ${
                      selectedId === row.task_id ? 'ring-2 ring-inset ring-blue-400' : ''
                    }`}
                  >
                    <td className="px-4 py-3 whitespace-nowrap text-xs text-gray-600 dark:text-gray-300">
                      {formatTimestamp(row.created_at)}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-900 dark:text-gray-100 max-w-xs">
                      {truncate(row.task, 100)}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={statusBadgeVariant(row.status, row.risk_level)}>{row.status}</Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge
                        variant={
                          row.risk_level === 'high'
                            ? 'danger'
                            : row.risk_level === 'medium'
                              ? 'warning'
                              : 'neutral'
                        }
                      >
                        {row.risk_level}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-right text-sm tabular-nums">
                      {row.estimated_cost_usd.toFixed(4)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-xs text-gray-600 dark:text-gray-300">
                      {formatTimestamp(row.completed_at)}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => loadDetail(row.task_id)}
                        className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
                      >
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </section>

        {(selectedId || detailLoading) && (
          <section className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4 md:p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Task detail</h2>
            {detailLoading && !detail ? (
              <p className="text-sm text-gray-500">Loading detail…</p>
            ) : detail ? (
              <div className="space-y-4 text-sm">
                <div className="flex flex-wrap gap-2 items-center">
                  <Badge variant={statusBadgeVariant(detail.status, detail.risk_level)}>{detail.status}</Badge>
                  <Badge
                    variant={
                      detail.risk_level === 'high'
                        ? 'danger'
                        : detail.risk_level === 'medium'
                          ? 'warning'
                          : 'neutral'
                    }
                  >
                    {detail.risk_level} risk
                  </Badge>
                  {detail.dry_run && <Badge variant="neutral">dry_run</Badge>}
                </div>
                <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">
                  <div>
                    <dt className="text-gray-500 dark:text-gray-400">task_id</dt>
                    <dd className="font-mono text-xs break-all">{detail.task_id}</dd>
                  </div>
                  <div>
                    <dt className="text-gray-500 dark:text-gray-400">estimated_cost_usd</dt>
                    <dd>{detail.estimated_cost_usd.toFixed(4)}</dd>
                  </div>
                  <div>
                    <dt className="text-gray-500 dark:text-gray-400">created_at</dt>
                    <dd>{formatTimestamp(detail.created_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-gray-500 dark:text-gray-400">completed_at</dt>
                    <dd>{formatTimestamp(detail.completed_at)}</dd>
                  </div>
                </dl>
                <div>
                  <dt className="text-gray-500 dark:text-gray-400 mb-1">task</dt>
                  <dd className="text-gray-900 dark:text-gray-100">{detail.task}</dd>
                </div>
                {detail.final_answer && (
                  <div>
                    <dt className="text-gray-500 dark:text-gray-400 mb-1">final_answer</dt>
                    <dd className="rounded border border-gray-200 dark:border-slate-600 bg-gray-50 dark:bg-slate-900 p-3 whitespace-pre-wrap">
                      {detail.final_answer}
                    </dd>
                  </div>
                )}
                {detail.error && (
                  <div>
                    <dt className="text-red-600 dark:text-red-400 mb-1">error</dt>
                    <dd className="text-red-700 dark:text-red-300">{detail.error}</dd>
                  </div>
                )}
                <div>
                  <dt className="text-gray-500 dark:text-gray-400 mb-1">plan</dt>
                  <JsonBlock value={detail.plan} />
                </div>
                <ReconcileSummary toolResults={detail.tool_results} />
                <div>
                  <dt className="text-gray-500 dark:text-gray-400 mb-1">tool_results</dt>
                  <JsonBlock value={detail.tool_results} expanded />
                </div>
                <div>
                  <dt className="text-gray-500 dark:text-gray-400 mb-1">review</dt>
                  <JsonBlock value={detail.review} />
                </div>
              </div>
            ) : (
              <p className="text-sm text-gray-500">Select a task to view details.</p>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
