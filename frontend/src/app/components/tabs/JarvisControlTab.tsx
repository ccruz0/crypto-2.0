'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  approveJarvisTask,
  getJarvisExecutionTask,
  listJarvisExecutionTasks,
  rejectJarvisTask,
  submitJarvisExecutionTask,
  type JarvisExecutionTaskDetail,
  type JarvisExecutionTaskSummary,
} from '@/app/api';
import JarvisAgentPanel from '@/app/components/jarvis/JarvisAgentPanel';
import JarvisOperationalStatus from '@/app/components/jarvis/JarvisOperationalStatus';

const POLL_MS = 10000;

function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const variant =
    normalized === 'completed'
      ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200'
      : normalized === 'failed' || normalized === 'cancelled'
        ? 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200'
        : normalized === 'waiting_for_approval'
          ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200'
          : 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200';
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${variant}`}>
      {status}
    </span>
  );
}

export default function JarvisControlTab() {
  const [objective, setObjective] = useState('');
  const [priority, setPriority] = useState<'low' | 'normal' | 'high'>('normal');
  const [approvalMode, setApprovalMode] = useState<'auto' | 'manual'>('auto');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);
  const [tasks, setTasks] = useState<JarvisExecutionTaskSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<JarvisExecutionTaskDetail | null>(null);

  const refreshList = useCallback(async () => {
    try {
      const res = await listJarvisExecutionTasks(20);
      setTasks(res.tasks || []);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const refreshDetail = useCallback(async (taskId: string) => {
    try {
      const d = await getJarvisExecutionTask(taskId);
      setDetail(d);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refreshList();
    const id = setInterval(refreshList, POLL_MS);
    return () => clearInterval(id);
  }, [refreshList]);

  useEffect(() => {
    if (!selectedId) return;
    refreshDetail(selectedId);
    const id = setInterval(() => refreshDetail(selectedId), POLL_MS);
    return () => clearInterval(id);
  }, [selectedId, refreshDetail]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!objective.trim()) return;
    setSubmitting(true);
    setError(null);
    setSubmitMessage(null);
    try {
      const res = await submitJarvisExecutionTask({
        objective: objective.trim(),
        priority,
        approval_mode: approvalMode,
        dry_run: true,
      });
      setSelectedId(res.task_id);
      setDetail(res as JarvisExecutionTaskDetail);
      setObjective('');
      setSubmitMessage(`Task ${res.task_id.slice(0, 8)} submitted — status: ${res.status}`);
      await refreshList();
    } catch (err) {
      const msg = String(err);
      setError(msg);
      setSubmitMessage(msg.includes('fetch') || msg.includes('503') ? 'Task not executed — Unable to reach Jarvis API.' : msg);
    } finally {
      setSubmitting(false);
    }
  };

  const onApprove = async () => {
    if (!selectedId) return;
    await approveJarvisTask(selectedId, { actor_id: 'dashboard', comment: 'approved via UI' });
    await refreshDetail(selectedId);
    await refreshList();
  };

  const onReject = async () => {
    if (!selectedId) return;
    await rejectJarvisTask(selectedId, { actor_id: 'dashboard', comment: 'rejected via UI' });
    await refreshDetail(selectedId);
    await refreshList();
  };

  return (
    <div data-testid="jarvis-tab" className="space-y-6">
      <JarvisOperationalStatus />

      <JarvisAgentPanel detail={detail} />

      <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-slate-800 p-4">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Submit Task</h2>
        <form onSubmit={onSubmit} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Objective</label>
            <textarea
              data-testid="jarvis-prompt-input"
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              rows={3}
              className="w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-slate-900 p-2 text-sm"
              placeholder="e.g. Inspect deployment health"
            />
          </div>
          <div className="flex flex-wrap gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Priority</label>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value as 'low' | 'normal' | 'high')}
                className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-slate-900 p-2 text-sm"
              >
                <option value="low">Low</option>
                <option value="normal">Normal</option>
                <option value="high">High</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Approval mode</label>
              <select
                value={approvalMode}
                onChange={(e) => setApprovalMode(e.target.value as 'auto' | 'manual')}
                className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-slate-900 p-2 text-sm"
              >
                <option value="auto">Auto (safe tasks only)</option>
                <option value="manual">Manual (always require approval)</option>
              </select>
            </div>
          </div>
          <button
            type="submit"
            data-testid="jarvis-submit-button"
            disabled={submitting || !objective.trim()}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
          >
            {submitting ? 'Submitting…' : 'Submit to Jarvis'}
          </button>
        </form>
        {(error || submitMessage) && (
          <p data-testid="jarvis-submit-message" className={`mt-2 text-sm ${error ? 'text-red-600' : 'text-green-700 dark:text-green-300'}`}>
            {error || submitMessage}
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-slate-800 p-4">
          <h3 className="font-semibold text-gray-900 dark:text-white mb-2">Recent tasks</h3>
          <ul className="space-y-2 max-h-96 overflow-y-auto">
            {tasks.map((t) => (
              <li key={t.task_id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(t.task_id)}
                  className={`w-full text-left p-2 rounded border text-sm ${
                    selectedId === t.task_id
                      ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                      : 'border-gray-200 dark:border-gray-600'
                  }`}
                >
                  <div className="font-medium truncate">{t.objective}</div>
                  <div className="flex items-center gap-2 mt-1">
                    <StatusBadge status={t.status} />
                    <span className="text-xs text-gray-500">{t.task_id.slice(0, 8)}</span>
                  </div>
                </button>
              </li>
            ))}
            {tasks.length === 0 && <p className="text-sm text-gray-500">No tasks yet.</p>}
          </ul>
        </div>

        <div className="lg:col-span-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-slate-800 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
            <h3 className="font-semibold text-gray-900 dark:text-white">Task execution</h3>
            <Link href="/jarvis/approval" className="text-xs text-blue-600 hover:underline dark:text-blue-400">
              Approval center →
            </Link>
          </div>
          {!detail ? (
            <p className="text-sm text-gray-500">Select a task to view plan, artifacts, and logs.</p>
          ) : (
            <div className="space-y-4 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={detail.status} />
                <span className="text-gray-500">Approval: {detail.approval_status}</span>
                <span className="text-gray-500">Est: ${detail.estimated_cost_usd?.toFixed(4)}</span>
                <span className="text-gray-500">Actual: ${detail.actual_cost_usd?.toFixed(4)}</span>
              </div>
              {detail.status === 'waiting_for_approval' && (
                <div className="flex gap-2">
                  <button type="button" onClick={onApprove} className="px-3 py-1 bg-green-600 text-white rounded text-xs">
                    Approve
                  </button>
                  <button type="button" onClick={onReject} className="px-3 py-1 bg-red-600 text-white rounded text-xs">
                    Reject
                  </button>
                </div>
              )}
              <div>
                <h4 className="font-medium mb-1">Plan</h4>
                <pre className="bg-gray-50 dark:bg-slate-900 p-2 rounded overflow-x-auto text-xs">
                  {JSON.stringify(detail.plan, null, 2)}
                </pre>
              </div>
              {detail.current_step && (
                <p>
                  <span className="font-medium">Current step:</span> {detail.current_step}
                </p>
              )}
              <div>
                <h4 className="font-medium mb-1">Artifacts ({detail.artifacts?.length || 0})</h4>
                <ul className="list-disc pl-5 text-xs text-gray-600 dark:text-gray-400">
                  {(detail.artifacts || []).map((a) => (
                    <li key={a.artifact_id}>{a.name} ({a.format})</li>
                  ))}
                </ul>
              </div>
              <div>
                <h4 className="font-medium mb-1">Execution log</h4>
                <ul className="space-y-1 text-xs max-h-40 overflow-y-auto">
                  {(detail.execution_log || []).map((log) => (
                    <li key={log.log_id} className="border-b border-gray-100 dark:border-gray-700 pb-1">
                      <span className="font-mono">{log.timestamp}</span> [{log.agent}/{log.tool}] {log.output_summary}
                    </li>
                  ))}
                </ul>
              </div>
              {detail.error && (
                <div className="text-xs text-red-600 bg-red-50 dark:bg-red-900/20 p-2 rounded">{detail.error}</div>
              )}
              {detail.final_answer && (
                <div>
                  <h4 className="font-medium mb-1">Result</h4>
                  <pre className="whitespace-pre-wrap text-xs bg-gray-50 dark:bg-slate-900 p-2 rounded">{detail.final_answer}</pre>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
