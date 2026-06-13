'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  getJarvisExecutionTask,
  getProposalEligibility,
  proposePatchFromInvestigation,
  type JarvisInvestigationDetail,
  type JarvisProposalEligibility,
  type JarvisProposalTaskDetail,
} from '@/app/api';
import {
  canGeneratePatchProposal,
  formatEligibilityReason,
  getMatchingFixTemplate,
  isPhase4bProposalsDisabled,
} from '@/app/components/tabs/proposalEligibilityUtils';

function ProposalStatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const variant =
    normalized === 'waiting_for_approval'
      ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200'
      : normalized === 'failed' || normalized === 'rejected'
        ? 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200'
        : normalized === 'approved' || normalized === 'completed'
          ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200'
          : 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200';
  return (
    <span
      data-testid="proposal-status-badge"
      className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${variant}`}
    >
      {status}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.min(100, Math.max(0, value));
  const color = pct >= 80 ? 'bg-green-500' : pct >= 50 ? 'bg-amber-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-200 dark:bg-slate-700 rounded overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono w-10 text-right">{pct.toFixed(0)}%</span>
    </div>
  );
}

export interface ProposalEligibilityPanelProps {
  investigationId: string;
  detail: JarvisInvestigationDetail;
  onProposalCreated?: () => void;
}

export default function ProposalEligibilityPanel({
  investigationId,
  detail,
  onProposalCreated,
}: ProposalEligibilityPanelProps) {
  const [eligibility, setEligibility] = useState<JarvisProposalEligibility | null>(null);
  const [loadingEligibility, setLoadingEligibility] = useState(false);
  const [proposing, setProposing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proposalTask, setProposalTask] = useState<JarvisProposalTaskDetail | null>(null);
  const [lastProposeResult, setLastProposeResult] = useState<JarvisProposalTaskDetail | null>(
    null,
  );

  const refreshEligibility = useCallback(async () => {
    setLoadingEligibility(true);
    setError(null);
    try {
      const result = await getProposalEligibility(investigationId);
      setEligibility(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load proposal eligibility');
      setEligibility(null);
    } finally {
      setLoadingEligibility(false);
    }
  }, [investigationId]);

  useEffect(() => {
    refreshEligibility();
  }, [refreshEligibility]);

  useEffect(() => {
    const taskId = detail.proposal_task_id?.trim();
    if (!taskId) {
      setProposalTask(null);
      return;
    }
    getJarvisExecutionTask(taskId)
      .then((task) => setProposalTask(task as JarvisProposalTaskDetail))
      .catch(() => setProposalTask(null));
  }, [detail.proposal_task_id]);

  const phase4bDisabled = eligibility ? isPhase4bProposalsDisabled(eligibility.reasons) : false;
  const canPropose = canGeneratePatchProposal(eligibility);
  const matchingTemplate = getMatchingFixTemplate(eligibility);
  const artifacts =
    lastProposeResult?.artifacts?.length
      ? lastProposeResult.artifacts
      : proposalTask?.artifacts || [];

  const handlePropose = async () => {
    if (!canPropose) return;
    setProposing(true);
    setError(null);
    try {
      const result = await proposePatchFromInvestigation(investigationId);
      setLastProposeResult(result);
      setProposalTask(result);
      await refreshEligibility();
      onProposalCreated?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to generate patch proposal');
    } finally {
      setProposing(false);
    }
  };

  const proposalStatus = detail.proposal_status?.trim();
  const proposalTaskId = detail.proposal_task_id?.trim();

  return (
    <section
      data-testid="proposal-eligibility-panel"
      className="rounded-lg border border-indigo-200 dark:border-indigo-800 bg-indigo-50/50 dark:bg-indigo-950/20 p-4 space-y-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-gray-900 dark:text-white">
          Phase 4B Patch Proposal
        </h4>
        {loadingEligibility ? (
          <span className="text-xs text-gray-500">Checking eligibility…</span>
        ) : eligibility ? (
          <span
            data-testid="eligibility-status"
            className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${
              eligibility.eligible
                ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200'
                : 'bg-gray-200 text-gray-700 dark:bg-slate-700 dark:text-gray-300'
            }`}
          >
            {eligibility.eligible ? 'Eligible' : 'Not eligible'}
          </span>
        ) : null}
      </div>

      <p
        data-testid="proposal-safety-notice"
        className="text-xs text-amber-800 dark:text-amber-200 bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 rounded px-2 py-1.5"
      >
        Proposal only. No patch is applied, no PR is created, no deploy is triggered.
      </p>

      {phase4bDisabled && (
        <p
          data-testid="phase4b-disabled-notice"
          className="text-xs text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-slate-900/60 border border-gray-200 dark:border-gray-700 rounded px-2 py-1.5"
        >
          Phase 4B is deployed but disabled in production.
        </p>
      )}

      {eligibility && (
        <>
          <div>
            <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Confidence</p>
            <ConfidenceBar value={eligibility.confidence} />
          </div>

          {eligibility.reasons.length > 0 && (
            <div data-testid="eligibility-reasons">
              <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Reasons</p>
              <ul className="list-disc list-inside text-xs text-gray-600 dark:text-gray-400 space-y-0.5">
                {eligibility.reasons.map((reason) => (
                  <li key={reason}>{formatEligibilityReason(reason)}</li>
                ))}
              </ul>
            </div>
          )}

          {matchingTemplate && (
            <div data-testid="matching-fix-template">
              <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                Matching fix template
              </p>
              <p className="text-xs font-mono text-gray-800 dark:text-gray-200">
                {matchingTemplate.fix_template_id}
              </p>
              <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5">{matchingTemplate.match}</p>
            </div>
          )}

          {eligibility.existing_proposal_task_id && (
            <p
              data-testid="existing-proposal-task-id"
              className="text-xs text-gray-600 dark:text-gray-400"
            >
              Existing proposal task:{' '}
              <span className="font-mono">{eligibility.existing_proposal_task_id}</span>
            </p>
          )}
        </>
      )}

      {(proposalTaskId || proposalStatus) && (
        <div data-testid="proposal-status-section" className="space-y-2 pt-1 border-t border-indigo-200 dark:border-indigo-800">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
              Proposal status
            </span>
            {proposalStatus && <ProposalStatusBadge status={proposalStatus} />}
          </div>
          {proposalTaskId && (
            <p className="text-xs text-gray-600 dark:text-gray-400">
              Task ID: <span className="font-mono">{proposalTaskId}</span>
            </p>
          )}
          <button
            type="button"
            data-testid="view-proposal-artifacts-button"
            disabled
            title="Artifact viewer coming soon"
            className="text-xs text-indigo-600 dark:text-indigo-400 underline disabled:opacity-50 disabled:no-underline"
          >
            View proposal artifacts
          </button>
          {artifacts.length > 0 && (
            <ul
              data-testid="proposal-artifact-names"
              className="list-disc list-inside text-xs text-gray-600 dark:text-gray-400"
            >
              {artifacts.map((artifact, idx) => (
                <li key={idx}>
                  {(artifact as { name?: string; path?: string }).name ||
                    (artifact as { name?: string; path?: string }).path ||
                    `artifact-${idx + 1}`}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="flex flex-col gap-1 pt-1">
        <button
          type="button"
          data-testid="generate-patch-proposal-button"
          onClick={handlePropose}
          disabled={!canPropose || proposing || loadingEligibility}
          title={
            phase4bDisabled
              ? 'Phase 4B is deployed but disabled in production.'
              : !canPropose
                ? 'Investigation is not eligible for patch proposal.'
                : undefined
          }
          className="self-start px-4 py-2 bg-indigo-600 text-white rounded text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {proposing ? 'Generating…' : 'Generate Patch Proposal'}
        </button>
        {phase4bDisabled && (
          <p className="text-xs text-gray-500" data-testid="generate-patch-proposal-help">
            Phase 4B is deployed but disabled in production.
          </p>
        )}
      </div>

      {error && (
        <p className="text-xs text-red-600 dark:text-red-400" data-testid="proposal-panel-error">
          {error}
        </p>
      )}
    </section>
  );
}
