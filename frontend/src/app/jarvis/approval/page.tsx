'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  approveChangeTask,
  fetchApprovalQueue,
  fetchChangeTask,
  rejectChangeTask,
  riskBadgeClass,
  type ApprovalQueueItem,
  type ChangeTaskDetail,
} from '@/lib/jarvisApproval';

export default function JarvisApprovalPage() {
  const [queue, setQueue] = useState<ApprovalQueueItem[]>([]);
  const [selected, setSelected] = useState<ChangeTaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const items = await fetchApprovalQueue();
      setQueue(items);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load approval queue');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadQueue();
  }, [loadQueue]);

  const selectTask = async (taskId: string) => {
    try {
      const detail = await fetchChangeTask(taskId);
      setSelected(detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load task');
    }
  };

  const handleApprove = async (taskId: string) => {
    setActionPending(true);
    try {
      const detail = await approveChangeTask(taskId, 'approval_center', 'Approved via Approval Center');
      setSelected(detail);
      await loadQueue();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Approve failed');
    } finally {
      setActionPending(false);
    }
  };

  const handleReject = async (taskId: string) => {
    setActionPending(true);
    try {
      const detail = await rejectChangeTask(taskId, 'approval_center', 'Rejected via Approval Center');
      setSelected(detail);
      await loadQueue();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Reject failed');
    } finally {
      setActionPending(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-6 py-4">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">Jarvis Approval Center</h1>
            <p className="text-sm text-slate-400">Phase 4 — review patches before any write execution</p>
          </div>
          <Link href="/monitoring" className="text-sm text-slate-400 hover:text-slate-200">
            ← Monitoring
          </Link>
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl gap-6 px-6 py-6 lg:grid-cols-2">
        <section className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-medium">Approval Queue</h2>
            <button
              type="button"
              onClick={() => void loadQueue()}
              className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
            >
              Refresh
            </button>
          </div>
          {loading && <p className="text-sm text-slate-500">Loading…</p>}
          {error && <p className="text-sm text-red-400">{error}</p>}
          {!loading && queue.length === 0 && (
            <p className="text-sm text-slate-500">No tasks awaiting approval.</p>
          )}
          <ul className="space-y-3">
            {queue.map((item) => (
              <li
                key={item.task_id}
                className="cursor-pointer rounded border border-slate-800 p-3 hover:border-slate-600"
                onClick={() => void selectTask(item.task_id)}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium line-clamp-2">{item.objective}</p>
                  <span className={`shrink-0 rounded px-2 py-0.5 text-xs ${riskBadgeClass(item.risk_score)}`}>
                    {item.risk_score ?? '—'}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-500 truncate">{item.patch_summary || 'No patch summary'}</p>
                <p className="mt-1 text-xs text-slate-600">{item.task_id.slice(0, 8)}…</p>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
          <h2 className="mb-4 font-medium">Task Detail</h2>
          {!selected && <p className="text-sm text-slate-500">Select a task from the queue.</p>}
          {selected && (
            <div className="space-y-4 text-sm">
              <div>
                <p className="text-xs uppercase text-slate-500">Objective</p>
                <p>{selected.objective}</p>
              </div>
              <div>
                <p className="text-xs uppercase text-slate-500">Status</p>
                <p>{selected.status}</p>
              </div>
              {(selected.review as { risk_score?: number })?.risk_score != null && (
                <div>
                  <p className="text-xs uppercase text-slate-500">Risk Score</p>
                  <span className={`rounded px-2 py-0.5 text-xs ${riskBadgeClass((selected.review as { risk_score?: number }).risk_score ?? null)}`}>
                    {(selected.review as { risk_score?: number }).risk_score}
                  </span>
                </div>
              )}
              <div>
                <p className="text-xs uppercase text-slate-500">Artifacts</p>
                <ul className="mt-1 space-y-1">
                  {(selected.artifacts ?? []).map((a) => (
                    <li key={String(a.artifact_id)} className="text-xs text-slate-400">
                      {String(a.standard_name ?? a.name)} (v{String(a.version ?? 1)})
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="text-xs uppercase text-slate-500">Review Findings</p>
                <ul className="mt-1 max-h-32 overflow-y-auto space-y-1">
                  {((selected.review as { findings?: Array<{ finding: string; severity: string }> })?.findings ?? []).map((f, i) => (
                    <li key={i} className="text-xs text-slate-400">
                      [{f.severity}] {f.finding}
                    </li>
                  ))}
                </ul>
              </div>
              {selected.status === 'waiting_for_approval' && (
                <div className="flex gap-2 pt-2">
                  <button
                    type="button"
                    disabled={actionPending}
                    onClick={() => void handleApprove(selected.task_id)}
                    className="rounded bg-emerald-700 px-3 py-1.5 text-xs font-medium hover:bg-emerald-600 disabled:opacity-50"
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    disabled={actionPending}
                    onClick={() => void handleReject(selected.task_id)}
                    className="rounded bg-red-800 px-3 py-1.5 text-xs font-medium hover:bg-red-700 disabled:opacity-50"
                  >
                    Reject
                  </button>
                </div>
              )}
              <p className="text-xs text-slate-600 border-t border-slate-800 pt-3">
                Patches are never auto-applied. Approval records intent only; write execution requires Phase 5.
              </p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
