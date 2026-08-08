'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
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
import {
  fetchApprovalQueue,
  fetchChangeTask,
  fetchLabTrialStatus,
  rejectChangeTask,
  sendChangeTaskToLab,
  type ApprovalQueueItem,
  type LabTrialStatus,
} from '@/lib/jarvisApproval';

const POLL_MS = 10000;

const PATCH_WORKFLOWS = new Set([
  'phase4_change',
  'phase4b_patch_proposal',
  'phase5_change',
]);

function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const variant =
    normalized === 'completed' || normalized === 'passed'
      ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200'
      : normalized === 'failed' ||
          normalized === 'cancelled' ||
          normalized === 'insufficient_evidence' ||
          normalized === 'refused'
        ? 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200'
        : normalized === 'waiting_for_approval' ||
            normalized === 'waiting_for_pr_approval' ||
            normalized === 'testing'
          ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200'
          : 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200';
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${variant}`}>
      {status}
    </span>
  );
}

function planWorkflowType(detail: JarvisExecutionTaskDetail | null): string {
  if (!detail?.plan || typeof detail.plan !== 'object') return '';
  const wt = (detail.plan as Record<string, unknown>).workflow_type;
  return typeof wt === 'string' ? wt : '';
}

function hasPatchArtifact(detail: JarvisExecutionTaskDetail | null): boolean {
  return (detail?.artifacts || []).some(
    (a) => a.name === 'patch.diff' || a.name?.startsWith('patch.diff'),
  );
}

function isPatchTrialTask(detail: JarvisExecutionTaskDetail | null): boolean {
  const wt = planWorkflowType(detail);
  return PATCH_WORKFLOWS.has(wt) || hasPatchArtifact(detail);
}

function ValidationOutcome({ validation }: { validation: JarvisExecutionTaskDetail['review'] }) {
  const outcome = validation?.validation;
  if (!outcome) return null;
  const checks = outcome.checks || [];
  const finalStatus = (outcome.final_status || 'unknown').toUpperCase();
  return (
    <div
      data-testid="jarvis-validation-outcome"
      className="rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-slate-900/60 p-3 space-y-2"
    >
      <h4 className="font-medium text-gray-900 dark:text-white">Validation</h4>
      <ul className="space-y-1 text-xs">
        {checks.map((check) => (
          <li key={check.label} className={check.passed ? 'text-green-700 dark:text-green-300' : 'text-red-700 dark:text-red-300'}>
            {check.passed ? '✅' : '❌'} {check.label}
          </li>
        ))}
      </ul>
      <p className="text-xs text-gray-600 dark:text-gray-400">
        <span className="font-medium">Final Status:</span> {finalStatus}
      </p>
      {outcome.explanation && (
        <p className="text-xs text-gray-600 dark:text-gray-400">{outcome.explanation}</p>
      )}
    </div>
  );
}

function LabResultPanel({ lab }: { lab: LabTrialStatus }) {
  const tone =
    lab.status === 'passed'
      ? 'border-green-300 bg-green-50 dark:border-green-800 dark:bg-green-900/20'
      : lab.status === 'failed' || lab.status === 'refused'
        ? 'border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-900/20'
        : lab.status === 'testing'
          ? 'border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-900/20'
          : 'border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900/40';
  return (
    <div data-testid="jarvis-lab-status" className={`rounded border p-3 space-y-2 ${tone}`}>
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="font-medium text-gray-900 dark:text-white">LAB trial</h4>
        <StatusBadge status={lab.status} />
        {lab.tests_passed && (
          <span className="text-xs font-medium text-green-700 dark:text-green-300">Tests passed</span>
        )}
      </div>
      <p className="text-xs text-gray-700 dark:text-gray-300">{lab.summary}</p>
      <p className="text-[11px] text-slate-500 dark:text-slate-400">{lab.mechanism_label}</p>
      {lab.changed_files?.length > 0 && (
        <p className="text-xs text-gray-600 dark:text-gray-400">
          Files: {lab.changed_files.slice(0, 8).join(', ')}
          {lab.changed_files.length > 8 ? '…' : ''}
        </p>
      )}
    </div>
  );
}

export default function JarvisControlTab() {
  const searchParams = useSearchParams();
  const taskFromUrl = searchParams.get('task');
  const [objective, setObjective] = useState('');
  const [priority, setPriority] = useState<'low' | 'normal' | 'high'>('normal');
  const [approvalMode, setApprovalMode] = useState<'auto' | 'manual'>('auto');
  const [submitting, setSubmitting] = useState(false);
  const [actionPending, setActionPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);
  const [tasks, setTasks] = useState<JarvisExecutionTaskSummary[]>([]);
  const [labQueue, setLabQueue] = useState<ApprovalQueueItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(() => taskFromUrl);
  const [detail, setDetail] = useState<JarvisExecutionTaskDetail | null>(null);
  const [labStatus, setLabStatus] = useState<LabTrialStatus | null>(null);

  const refreshList = useCallback(async () => {
    try {
      const [res, queue] = await Promise.all([
        listJarvisExecutionTasks(20),
        fetchApprovalQueue(50).catch(() => [] as ApprovalQueueItem[]),
      ]);
      setTasks(res.tasks || []);
      setLabQueue(queue);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const refreshDetail = useCallback(async (taskId: string) => {
    try {
      // Prefer change detail when this is a patch trial (has lab_trial / workflow).
      let d: JarvisExecutionTaskDetail | null = null;
      let lab: LabTrialStatus | null = null;
      try {
        const change = await fetchChangeTask(taskId);
        d = {
          ...change,
          plan: change.plan || { workflow_type: change.workflow_type },
          artifacts: (change.artifacts || []).map((a) => ({
            artifact_id: String(a.artifact_id || a.name || ''),
            name: String(a.name || ''),
            format: String(a.format || 'text'),
            preview: typeof a.preview === 'string' ? a.preview : undefined,
          })),
          execution_log: (change.execution_log || []) as JarvisExecutionTaskDetail['execution_log'],
          review: change.review as JarvisExecutionTaskDetail['review'],
          approval_status: change.approval_status,
          current_step: change.current_step,
          error: change.error,
          final_answer: change.final_answer || undefined,
        };
        lab = change.lab_trial || (await fetchLabTrialStatus(taskId));
      } catch {
        d = await getJarvisExecutionTask(taskId);
        try {
          lab = await fetchLabTrialStatus(taskId);
        } catch {
          lab = null;
        }
      }
      setDetail(d);
      setLabStatus(lab);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  // Deep-link: ?tab=jarvis&task=<id> from Improvement Execute → Approve investigation
  useEffect(() => {
    if (taskFromUrl) setSelectedId(taskFromUrl);
  }, [taskFromUrl]);

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

  const investigationWaiting = tasks.filter((t) => {
    if (t.status.toLowerCase() !== 'waiting_for_approval') return false;
    const inLabQueue = labQueue.find((q) => q.task_id === t.task_id);
    // Absent from the change approval queue: do not assume investigation —
    // patch trials can fall out of the queue window and must not get
    // "Approve investigation".
    if (!inLabQueue) return false;
    // Change/patch workflows belong in Ready for LAB, not investigation Approve.
    if (PATCH_WORKFLOWS.has(inLabQueue.workflow_type || '')) return false;
    if (
      inLabQueue.can_send_to_lab ||
      (inLabQueue.lab_trial_status && inLabQueue.lab_trial_status !== 'not_started')
    ) {
      return false;
    }
    return true;
  });

  const readyForLab = labQueue.filter((q) => {
    const isPatchWorkflow = PATCH_WORKFLOWS.has(q.workflow_type || '');
    const hasLabActivity =
      q.lab_trial_status === 'testing' ||
      q.lab_trial_status === 'passed' ||
      q.lab_trial_status === 'failed' ||
      q.lab_trial_status === 'refused' ||
      q.can_send_to_lab;
    if (q.status === 'waiting_for_pr_approval') return true;
    if (q.status === 'waiting_for_approval' && (isPatchWorkflow || hasLabActivity)) return true;
    if (
      q.status === 'applying_patch' ||
      q.status === 'sandbox_testing'
    ) {
      return isPatchWorkflow || hasLabActivity;
    }
    return hasLabActivity;
  });

  // Prefer a Waiting-on-you / Ready-for-LAB task when nothing is selected.
  useEffect(() => {
    if (selectedId || taskFromUrl) return;
    const firstLab = labQueue.find(
      (q) => q.can_send_to_lab || q.status === 'waiting_for_approval',
    );
    if (firstLab) {
      setSelectedId(firstLab.task_id);
      return;
    }
    const firstWaiting = tasks.find((t) => {
      if (t.status.toLowerCase() !== 'waiting_for_approval') return false;
      const inLabQueue = labQueue.find((q) => q.task_id === t.task_id);
      if (!inLabQueue) return false;
      if (PATCH_WORKFLOWS.has(inLabQueue.workflow_type || '')) return false;
      if (
        inLabQueue.can_send_to_lab ||
        (inLabQueue.lab_trial_status && inLabQueue.lab_trial_status !== 'not_started')
      ) {
        return false;
      }
      return true;
    });
    if (!firstWaiting) return;
    setSelectedId(firstWaiting.task_id);
  }, [selectedId, taskFromUrl, labQueue, tasks]);

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

  const onApproveInvestigation = async () => {
    if (!selectedId) return;
    setActionPending(true);
    setError(null);
    try {
      await approveJarvisTask(selectedId, { actor_id: 'dashboard', comment: 'approved via UI' });
      await refreshDetail(selectedId);
      await refreshList();
    } catch (e) {
      setError(String(e));
    } finally {
      setActionPending(false);
    }
  };

  const onSendToLab = async () => {
    if (!selectedId) return;
    setActionPending(true);
    setError(null);
    try {
      await sendChangeTaskToLab(selectedId, 'dashboard', 'Send to LAB via Ops Jarvis');
      await refreshDetail(selectedId);
      await refreshList();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      await refreshDetail(selectedId);
    } finally {
      setActionPending(false);
    }
  };

  const onReject = async () => {
    if (!selectedId) return;
    setActionPending(true);
    setError(null);
    try {
      if (isPatchTrialTask(detail)) {
        await rejectChangeTask(selectedId, 'dashboard', 'rejected via Ops Jarvis');
      } else {
        await rejectJarvisTask(selectedId, { actor_id: 'dashboard', comment: 'rejected via UI' });
      }
      await refreshDetail(selectedId);
      await refreshList();
    } catch (e) {
      setError(String(e));
    } finally {
      setActionPending(false);
    }
  };

  const patchTrial = isPatchTrialTask(detail);
  const showSendToLab =
    patchTrial &&
    (detail?.status === 'waiting_for_approval' ||
      labStatus?.status === 'refused' ||
      labStatus?.status === 'failed' ||
      labStatus?.can_send_to_lab);
  const showApproveInvestigation =
    !patchTrial && detail?.status === 'waiting_for_approval';
  const labPassed = labStatus?.status === 'passed' || detail?.current_step === 'lab_passed_awaiting_promote';

  return (
    <div data-testid="jarvis-tab" className="space-y-6">
      <JarvisOperationalStatus />

      <JarvisAgentPanel detail={detail} />

      {readyForLab.length > 0 && (
        <div
          data-testid="jarvis-ready-for-lab"
          className="rounded-lg border border-indigo-300 dark:border-indigo-700 bg-indigo-50 dark:bg-indigo-900/20 p-4"
        >
          <h2 className="text-lg font-semibold text-indigo-900 dark:text-indigo-100 mb-1">
            Ready for LAB / LAB results
          </h2>
          <p className="text-xs text-indigo-800 dark:text-indigo-200/80 mb-3">
            Patch trials you can send to LAB (isolated apply + tests). This is not production and does
            not open a PR yet — Promote comes later when LAB is green.
          </p>
          <ul className="space-y-2">
            {readyForLab.map((t) => (
              <li key={t.task_id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(t.task_id)}
                  className={`w-full text-left p-2 rounded border text-sm ${
                    selectedId === t.task_id
                      ? 'border-indigo-600 bg-white dark:bg-slate-900'
                      : 'border-indigo-200 dark:border-indigo-800 bg-white/70 dark:bg-slate-900/40'
                  }`}
                >
                  <div className="font-medium truncate">{t.objective}</div>
                  <div className="flex flex-wrap items-center gap-2 mt-1">
                    <StatusBadge status={t.lab_trial_status || t.status} />
                    {t.can_send_to_lab && (
                      <span className="text-xs text-indigo-700 dark:text-indigo-300">Send to LAB available</span>
                    )}
                    <span className="text-xs text-gray-500">{t.task_id.slice(0, 8)}</span>
                  </div>
                  {t.lab_trial_summary && (
                    <p className="text-[11px] text-slate-600 dark:text-slate-400 mt-1 line-clamp-2">
                      {t.lab_trial_summary}
                    </p>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {investigationWaiting.length > 0 && (
        <div
          data-testid="jarvis-waiting-on-you"
          className="rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 p-4"
        >
          <h2 className="text-lg font-semibold text-amber-900 dark:text-amber-100 mb-1">
            Waiting on you
          </h2>
          <p className="text-xs text-amber-800 dark:text-amber-200/80 mb-3">
            Dry-run investigations that need your go-ahead to continue the plan. This is not Send to LAB
            (use Ready for LAB above when a real patch trial is available). For Phase-5 sandbox/PR gates,
            use Advanced change gates.
          </p>
          <ul className="space-y-2">
            {investigationWaiting.map((t) => (
              <li key={t.task_id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(t.task_id)}
                  className={`w-full text-left p-2 rounded border text-sm ${
                    selectedId === t.task_id
                      ? 'border-amber-600 bg-white dark:bg-slate-900'
                      : 'border-amber-200 dark:border-amber-800 bg-white/70 dark:bg-slate-900/40'
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
          </ul>
        </div>
      )}

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
            <Link
              href="/jarvis/approval"
              className="text-xs text-slate-500 hover:underline dark:text-slate-400"
              title="Phase-5 sandbox / PR gates only — not for dry-run investigation approval"
            >
              Advanced change gates →
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
              <ValidationOutcome validation={detail.review} />
              {labStatus && <LabResultPanel lab={labStatus} />}

              {showSendToLab && (
                <div className="space-y-2" data-testid="jarvis-send-to-lab-panel">
                  <p className="text-xs text-indigo-800 dark:text-indigo-200/90 bg-indigo-50 dark:bg-indigo-900/20 rounded px-2 py-1.5">
                    <span className="font-medium">Send to LAB</span> applies this patch in an isolated
                    sandbox and runs tests. It does not write to production or open a PR. Stub/TODO
                    patches are refused.
                  </p>
                  {labStatus && !labStatus.can_send_to_lab && labStatus.ineligible_reason && (
                    <p
                      data-testid="jarvis-lab-ineligible"
                      className="text-xs text-amber-800 dark:text-amber-200 bg-amber-50 dark:bg-amber-900/20 rounded px-2 py-1.5"
                    >
                      {labStatus.ineligible_reason}
                    </p>
                  )}
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      data-testid="jarvis-send-to-lab"
                      onClick={onSendToLab}
                      disabled={actionPending || !labStatus?.can_send_to_lab}
                      title={
                        labStatus?.can_send_to_lab
                          ? 'Send to LAB'
                          : labStatus?.ineligible_reason || 'Not eligible for LAB'
                      }
                      className="px-3 py-1 bg-indigo-600 text-white rounded text-xs disabled:opacity-50"
                    >
                      {actionPending ? 'Sending…' : 'Send to LAB'}
                    </button>
                    <button
                      type="button"
                      data-testid="jarvis-reject-task"
                      onClick={onReject}
                      disabled={actionPending}
                      className="px-3 py-1 bg-red-600 text-white rounded text-xs disabled:opacity-50"
                    >
                      Reject
                    </button>
                    <button
                      type="button"
                      data-testid="jarvis-promote-disabled"
                      disabled
                      title={labStatus?.promote_hint || 'Promote arrives in Phase C'}
                      className="px-3 py-1 bg-slate-400 text-white rounded text-xs cursor-not-allowed opacity-60"
                    >
                      Promote to production
                    </button>
                  </div>
                </div>
              )}

              {labPassed && !showSendToLab && (
                <div className="space-y-2" data-testid="jarvis-lab-passed-panel">
                  <p className="text-xs text-green-800 dark:text-green-200 bg-green-50 dark:bg-green-900/20 rounded px-2 py-1.5">
                    LAB passed. Promote to production (open PR for you to merge/deploy) ships in Phase C —
                    button stays disabled for now.
                  </p>
                  <button
                    type="button"
                    data-testid="jarvis-promote-disabled"
                    disabled
                    className="px-3 py-1 bg-slate-400 text-white rounded text-xs cursor-not-allowed opacity-60"
                  >
                    Promote to production
                  </button>
                </div>
              )}

              {showApproveInvestigation && (
                <div className="space-y-2">
                  <p className="text-xs text-amber-800 dark:text-amber-200/90 bg-amber-50 dark:bg-amber-900/20 rounded px-2 py-1.5">
                    Approving continues this dry-run investigation plan only. It does not Send to LAB or
                    promote to production.
                  </p>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      data-testid="jarvis-approve-investigation"
                      onClick={onApproveInvestigation}
                      disabled={actionPending}
                      className="px-3 py-1 bg-green-600 text-white rounded text-xs disabled:opacity-50"
                    >
                      Approve investigation
                    </button>
                    <button
                      type="button"
                      data-testid="jarvis-reject-task"
                      onClick={onReject}
                      disabled={actionPending}
                      className="px-3 py-1 bg-red-600 text-white rounded text-xs disabled:opacity-50"
                    >
                      Reject
                    </button>
                  </div>
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
