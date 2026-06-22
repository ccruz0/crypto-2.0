'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  createSelfHealingAcwTask,
  createSelfHealingFixPr,
  getSelfHealingRecommendation,
  recordSelfHealingDecision,
  type JarvisSelfHealingRecommendation,
} from '@/app/api';

const RISK_STYLES: Record<string, string> = {
  low: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200',
  medium: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  high: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200',
};

const SEVERITY_STYLES: Record<string, string> = {
  low: 'bg-gray-100 text-gray-700 dark:bg-slate-700 dark:text-gray-200',
  medium: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  high: 'bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-200',
  critical: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200',
};

function Pill({ label, value, styles }: { label: string; value: string; styles?: Record<string, string> }) {
  const cls = styles?.[value] || 'bg-gray-100 text-gray-700 dark:bg-slate-700 dark:text-gray-200';
  return (
    <span className="inline-flex items-center gap-1 text-xs">
      <span className="text-gray-500 dark:text-gray-400">{label}:</span>
      <span className={`px-2 py-0.5 rounded font-semibold ${cls}`}>{value}</span>
    </span>
  );
}

export interface SelfHealingPanelProps {
  investigationId: string;
  status: string;
  onAcwTaskCreated?: () => void;
}

export default function SelfHealingPanel({
  investigationId,
  status,
  onAcwTaskCreated,
}: SelfHealingPanelProps) {
  const [rec, setRec] = useState<JarvisSelfHealingRecommendation | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const completed = status?.toLowerCase() === 'completed';

  const load = useCallback(async () => {
    if (!completed) {
      setRec(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setRec(await getSelfHealingRecommendation(investigationId));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load recommendation');
      setRec(null);
    } finally {
      setLoading(false);
    }
  }, [investigationId, completed]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreateAcw = async () => {
    setBusy('acw');
    setError(null);
    setNotice(null);
    try {
      const result = await createSelfHealingAcwTask(investigationId);
      const taskId = (result.acw_task as { task_id?: string })?.task_id || 'unknown';
      setNotice(`ACW task prepared (${taskId}). Awaiting approval in the Approval Center.`);
      onAcwTaskCreated?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create ACW task');
    } finally {
      setBusy(null);
    }
  };

  const handleCreateFixPr = async () => {
    setBusy('pr');
    setError(null);
    setNotice(null);
    try {
      const task = await createSelfHealingFixPr(investigationId);
      setNotice(`Fix proposal created (${task.task_id}). Awaiting approval — no PR until approved.`);
      onAcwTaskCreated?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create fix proposal');
    } finally {
      setBusy(null);
    }
  };

  const handleDecision = async (decision: 'ignore' | 'investigate_further') => {
    setBusy(decision);
    setError(null);
    setNotice(null);
    try {
      const result = await recordSelfHealingDecision(investigationId, decision);
      if (decision === 'ignore') {
        setNotice('Recommendation ignored.');
      } else {
        setNotice(
          result.suggested_objective
            ? `Suggested follow-up: ${result.suggested_objective}`
            : 'Marked for further investigation.',
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to record decision');
    } finally {
      setBusy(null);
    }
  };

  if (!completed) return null;

  return (
    <section
      data-testid="self-healing-panel"
      className="rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-950/20 p-4 space-y-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-gray-900 dark:text-white">Self-Healing Advisor</h4>
        {rec && (
          <span
            data-testid="self-healing-acw-status"
            className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${
              rec.acw_ready
                ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200'
                : 'bg-gray-200 text-gray-700 dark:bg-slate-700 dark:text-gray-300'
            }`}
          >
            {rec.acw_ready ? 'ACW-ready' : 'Advisory only'}
          </span>
        )}
      </div>

      <p
        data-testid="self-healing-safety-notice"
        className="text-xs text-amber-800 dark:text-amber-200 bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 rounded px-2 py-1.5"
      >
        Recommendation only. Jarvis never applies code, merges, deploys, or trades. Human approval is
        mandatory.
      </p>

      {loading && <p className="text-xs text-gray-500">Generating recommendation…</p>}

      {rec && (
        <>
          <div>
            <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Recommended Fix</p>
            <p data-testid="self-healing-proposed-fix" className="text-sm text-gray-800 dark:text-gray-200">
              {rec.recommendation.proposed_fix || 'No concrete fix available.'}
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <Pill label="Severity" value={rec.assessment.severity} styles={SEVERITY_STYLES} />
            <Pill label="Blast radius" value={rec.assessment.blast_radius} />
            <Pill label="Fixability" value={rec.assessment.fixability} />
            <Pill label="Risk" value={rec.recommendation.estimated_risk} styles={RISK_STYLES} />
            <Pill label="Effort" value={rec.recommendation.estimated_effort} />
          </div>

          {rec.recommendation.affected_files.length > 0 && (
            <div data-testid="self-healing-affected-files">
              <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Affected Files</p>
              <ul className="list-disc list-inside text-xs font-mono text-gray-700 dark:text-gray-300">
                {rec.recommendation.affected_files.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </div>
          )}

          {!rec.safety.allowed && (
            <p
              data-testid="self-healing-blocked-notice"
              className="text-xs text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded px-2 py-1.5"
            >
              Blocked for automatic fix ({rec.safety.blocked_domains.join(', ') || 'sensitive domain'}).
              Requires explicit human approval.
            </p>
          )}

          {rec.safety.allowed && !rec.acw_ready && rec.acw.reasons.length > 0 && (
            <div data-testid="self-healing-acw-reasons">
              <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                Not ACW-ready because
              </p>
              <ul className="list-disc list-inside text-xs text-gray-600 dark:text-gray-400">
                {rec.acw.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          )}

          {rec.acw_ready && rec.acw.implementation_plan.length > 0 && (
            <div data-testid="self-healing-plan">
              <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                Proposed Implementation Plan
              </p>
              <ol className="list-decimal list-inside text-xs text-gray-600 dark:text-gray-400 space-y-0.5">
                {rec.acw.implementation_plan.map((step, idx) => (
                  <li key={idx}>{step}</li>
                ))}
              </ol>
            </div>
          )}

          <div className="flex flex-wrap gap-2 pt-1">
            <button
              type="button"
              data-testid="self-healing-create-acw-button"
              onClick={handleCreateAcw}
              disabled={!rec.acw_ready || busy !== null}
              title={rec.acw_ready ? undefined : 'Recommendation is not ACW-ready'}
              className="px-3 py-1.5 bg-emerald-600 text-white rounded text-xs font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {busy === 'acw' ? 'Creating…' : 'Create ACW Task'}
            </button>
            <button
              type="button"
              data-testid="self-healing-create-pr-button"
              onClick={handleCreateFixPr}
              disabled={!rec.available_actions.includes('create_fix_pr') || busy !== null}
              className="px-3 py-1.5 bg-indigo-600 text-white rounded text-xs font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {busy === 'pr' ? 'Creating…' : 'Create Fix PR'}
            </button>
            <button
              type="button"
              data-testid="self-healing-investigate-button"
              onClick={() => handleDecision('investigate_further')}
              disabled={busy !== null}
              className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded text-xs disabled:opacity-50"
            >
              Investigate Further
            </button>
            <button
              type="button"
              data-testid="self-healing-ignore-button"
              onClick={() => handleDecision('ignore')}
              disabled={busy !== null}
              className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded text-xs disabled:opacity-50"
            >
              Ignore
            </button>
          </div>
        </>
      )}

      {notice && (
        <p data-testid="self-healing-notice" className="text-xs text-emerald-700 dark:text-emerald-300">
          {notice}
        </p>
      )}
      {error && (
        <p data-testid="self-healing-error" className="text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
    </section>
  );
}
