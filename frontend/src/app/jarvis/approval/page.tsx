'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  approvePatchApply,
  approvePrCreation,
  fetchApprovalQueue,
  fetchChangeTask,
  fetchPhase5Status,
  fetchSafetyStatus,
  gateLabel,
  rejectChangeTask,
  riskBadgeClass,
  type ApprovalQueueItem,
  type ChangeTaskDetail,
  type Phase5Status,
  type SafetyStatus,
} from '@/lib/jarvisApproval';

export default function JarvisApprovalPage() {
  const [queue, setQueue] = useState<ApprovalQueueItem[]>([]);
  const [selected, setSelected] = useState<ChangeTaskDetail | null>(null);
  const [phase5, setPhase5] = useState<Phase5Status | null>(null);
  const [safety, setSafety] = useState<SafetyStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [items, safetyStatus] = await Promise.all([fetchApprovalQueue(), fetchSafetyStatus()]);
      setQueue(items);
      setSafety(safetyStatus);
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
      const [detail, p5] = await Promise.all([fetchChangeTask(taskId), fetchPhase5Status(taskId)]);
      setSelected(detail);
      setPhase5(p5);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load task');
    }
  };

  const refreshSelected = async (taskId: string) => {
    const [detail, p5] = await Promise.all([fetchChangeTask(taskId), fetchPhase5Status(taskId)]);
    setSelected(detail);
    setPhase5(p5);
    await loadQueue();
  };

  const handleApproveApply = async (taskId: string) => {
    setActionPending(true);
    try {
      await approvePatchApply(taskId, 'approval_center', 'Gate 1: sandbox apply approved');
      await refreshSelected(taskId);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Approve apply failed');
    } finally {
      setActionPending(false);
    }
  };

  const handleApprovePr = async (taskId: string) => {
    setActionPending(true);
    try {
      await approvePrCreation(taskId, 'approval_center', 'Gate 2: PR creation approved');
      await refreshSelected(taskId);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Approve PR failed');
    } finally {
      setActionPending(false);
    }
  };

  const handleReject = async (taskId: string) => {
    setActionPending(true);
    try {
      await rejectChangeTask(taskId, 'approval_center', 'Rejected via Approval Center');
      await refreshSelected(taskId);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Reject failed');
    } finally {
      setActionPending(false);
    }
  };

  const patchArtifact = selected?.artifacts?.find(
    (a) => a.standard_name === 'patch.diff' || String(a.name).startsWith('patch.diff')
  );

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-6 py-4">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">Jarvis Approval Center</h1>
            <p className="text-sm text-slate-400">Phase 5 — two-gate approval for sandbox apply and PR creation</p>
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
                <p className="mt-1 text-xs text-amber-400/80">{gateLabel(item.status)}</p>
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
                <p className="text-xs uppercase text-slate-500">Status / Gate</p>
                <p>{gateLabel(selected.status)}</p>
              </div>

              {safety && (
                <div className="rounded border border-slate-700 bg-slate-900 p-3">
                  <p className="text-xs uppercase text-slate-500 mb-2">Current Safety Status</p>
                  <ul className="space-y-1 text-xs text-slate-400">
                    <li>Patch apply: {safety.phase5.patch_apply_enabled ? 'enabled' : 'disabled'}</li>
                    <li>PR creation: {safety.phase5.pr_creation_enabled ? 'enabled' : 'disabled'}</li>
                    <li>GitHub write: {safety.phase5.github_write_enabled ? 'enabled' : 'disabled'}</li>
                    <li>Double approval: {safety.phase5.double_approval_required ? 'required' : 'optional'}</li>
                  </ul>
                </div>
              )}

              {(selected.review as { risk_score?: number })?.risk_score != null && (
                <div>
                  <p className="text-xs uppercase text-slate-500">Risk Score</p>
                  <span className={`rounded px-2 py-0.5 text-xs ${riskBadgeClass((selected.review as { risk_score?: number }).risk_score ?? null)}`}>
                    {(selected.review as { risk_score?: number }).risk_score}
                  </span>
                </div>
              )}

              {patchArtifact && (
                <div>
                  <p className="text-xs uppercase text-slate-500">Patch Preview</p>
                  <pre className="mt-1 max-h-32 overflow-auto rounded bg-slate-950 p-2 text-xs text-slate-400">
                    {String(patchArtifact.preview ?? 'No preview available').slice(0, 800)}
                  </pre>
                </div>
              )}

              {phase5 && phase5.changed_files.length > 0 && (
                <div>
                  <p className="text-xs uppercase text-slate-500">Changed Files (sandbox)</p>
                  <ul className="mt-1 max-h-24 overflow-y-auto space-y-1">
                    {phase5.changed_files.map((f) => (
                      <li key={f} className="text-xs text-slate-400">{f}</li>
                    ))}
                  </ul>
                </div>
              )}

              {phase5?.test_results && Object.keys(phase5.test_results).length > 0 && (
                <div>
                  <p className="text-xs uppercase text-slate-500">Test Results</p>
                  <p className="text-xs text-slate-400">
                    Passed: {phase5.tests_passed ? 'yes' : 'no'}
                  </p>
                </div>
              )}

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

              {selected.approvals && selected.approvals.length > 0 && (
                <div>
                  <p className="text-xs uppercase text-slate-500">Approval History</p>
                  <ul className="mt-1 space-y-1">
                    {selected.approvals.map((a) => (
                      <li key={String(a.approval_id)} className="text-xs text-slate-400">
                        {String(a.decision)} by {String(a.actor_id)} — {String(a.created_at ?? '')}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {phase5?.pr_url && (
                <div>
                  <p className="text-xs uppercase text-slate-500">PR Link</p>
                  <a href={phase5.pr_url} className="text-xs text-blue-400 hover:underline" target="_blank" rel="noreferrer">
                    {phase5.pr_url}
                  </a>
                </div>
              )}

              <div className="space-y-2 border-t border-slate-800 pt-3">
                <p className="text-xs uppercase text-slate-500">Approval Actions</p>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={actionPending || !phase5?.can_approve_apply}
                    onClick={() => void handleApproveApply(selected.task_id)}
                    className="rounded bg-emerald-700 px-3 py-1.5 text-xs font-medium hover:bg-emerald-600 disabled:opacity-40"
                    title={phase5?.can_approve_apply ? 'Approve sandbox apply' : 'Prerequisites not met or disabled'}
                  >
                    Approve sandbox apply
                  </button>
                  <button
                    type="button"
                    disabled={actionPending || !phase5?.can_approve_pr}
                    onClick={() => void handleApprovePr(selected.task_id)}
                    className="rounded bg-blue-700 px-3 py-1.5 text-xs font-medium hover:bg-blue-600 disabled:opacity-40"
                    title={phase5?.can_approve_pr ? 'Approve PR creation' : 'Tests must pass and flags must be enabled'}
                  >
                    Approve PR creation
                  </button>
                  <button
                    type="button"
                    disabled={actionPending}
                    onClick={() => void handleReject(selected.task_id)}
                    className="rounded bg-red-800 px-3 py-1.5 text-xs font-medium hover:bg-red-700 disabled:opacity-50"
                  >
                    Reject task
                  </button>
                </div>
              </div>

              <p className="text-xs text-slate-600 border-t border-slate-800 pt-3">
                Patches apply only in isolated sandboxes. PR creation requires both approvals and enabled env flags.
                Merge and deploy are permanently disabled.
              </p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
