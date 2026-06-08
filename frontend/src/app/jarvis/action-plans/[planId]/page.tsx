'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import Badge from '@/components/ui/Badge';
import { createJarvisDecision, getJarvisActionPlan, JarvisActionPlanDetail } from '@/lib/api';

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function severityVariant(severity: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (severity === 'critical' || severity === 'high') return 'danger';
  if (severity === 'medium') return 'warning';
  return 'neutral';
}

function statusVariant(status: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (status === 'approved') return 'success';
  if (status === 'rejected') return 'danger';
  return 'warning';
}

export default function JarvisActionPlanDetailPage() {
  const params = useParams();
  const planId = typeof params.planId === 'string' ? params.planId : '';
  const [detail, setDetail] = useState<JarvisActionPlanDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decisionNote, setDecisionNote] = useState('');

  const loadDetail = useCallback(async () => {
    if (!planId) return;
    setLoading(true);
    try {
      const data = await getJarvisActionPlan(planId);
      setDetail(data);
      setError(null);
    } catch (err) {
      setDetail(null);
      setError(err instanceof Error ? err.message : 'Failed to load action plan');
    } finally {
      setLoading(false);
    }
  }, [planId]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  const sourceHref =
    detail?.source_type === 'aws_audit' && detail.source_id
      ? `/jarvis/audits/${detail.source_id}`
      : detail?.source_type === 'crypto_audit' && detail.source_id
        ? `/jarvis/crypto-audits/${detail.source_id}`
        : detail?.source_type === 'executive_dashboard'
          ? '/jarvis/executive'
          : null;

  const recordDecision = async (decision: 'approved' | 'rejected' | 'deferred') => {
    if (!detail) return;
    setRecording(true);
    try {
      const primaryAction = detail.actions?.[0]?.title || 'Action plan review';
      const result = await createJarvisDecision({
        source_type: detail.source_type,
        source_id: detail.source_id,
        plan_id: detail.plan_id,
        decision,
        decision_reason: decisionNote || primaryAction,
        reviewed_by: 'Carlos',
      });
      setError(null);
      await loadDetail();
      window.location.href = `/jarvis/decisions/${result.decision_id}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to record decision');
    } finally {
      setRecording(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <div className="container mx-auto p-4 md:p-8 max-w-7xl">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Action Plan Detail</h1>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1 font-mono">{planId}</p>
          </div>
          <Link
            href="/jarvis/action-plans"
            className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
          >
            ← All action plans
          </Link>
        </div>

        <div className="mb-4 rounded border border-amber-300 bg-amber-50 dark:bg-amber-950/30 text-amber-900 dark:text-amber-200 px-4 py-3 text-sm">
          Recommendations only. No infrastructure changes, trades, or balance modifications are performed
          automatically. Human review and approval required.
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-300 bg-red-50 dark:bg-red-950/30 text-red-800 dark:text-red-200 px-4 py-3 text-sm">
            {error}
          </div>
        )}

        {loading && !detail ? (
          <p className="text-sm text-gray-500">Loading action plan…</p>
        ) : detail ? (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="rounded-lg border bg-white dark:bg-slate-800 dark:border-slate-700 p-4">
                <p className="text-xs text-gray-500 uppercase">Severity</p>
                <div className="mt-2">
                  <Badge variant={severityVariant(detail.severity)}>{detail.severity}</Badge>
                </div>
              </div>
              <div className="rounded-lg border bg-white dark:bg-slate-800 dark:border-slate-700 p-4">
                <p className="text-xs text-gray-500 uppercase">Status</p>
                <div className="mt-2">
                  <Badge variant={statusVariant(detail.status)}>{detail.status}</Badge>
                </div>
              </div>
              <div className="rounded-lg border bg-white dark:bg-slate-800 dark:border-slate-700 p-4">
                <p className="text-xs text-gray-500 uppercase">Est. savings/mo</p>
                <p className="mt-2 text-lg font-mono tabular-nums">
                  ${detail.estimated_savings_usd.toFixed(2)}
                </p>
              </div>
              <div className="rounded-lg border bg-white dark:bg-slate-800 dark:border-slate-700 p-4">
                <p className="text-xs text-gray-500 uppercase">Created</p>
                <p className="mt-2 text-sm">{formatTimestamp(detail.created_at)}</p>
              </div>
            </div>

            <div className="rounded-lg border bg-white dark:bg-slate-800 dark:border-slate-700 p-4">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">Source audit</h2>
              <p className="text-sm text-gray-600 dark:text-gray-300">
                Type: <span className="font-mono">{detail.source_type || '—'}</span>
              </p>
              {sourceHref ? (
                <Link href={sourceHref} className="text-sm text-blue-600 dark:text-blue-400 hover:underline mt-1 inline-block">
                  View source audit ({detail.source_id})
                </Link>
              ) : (
                <p className="text-sm font-mono text-gray-500 mt-1">{detail.source_id || '—'}</p>
              )}
            </div>

            <div className="rounded-lg border bg-white dark:bg-slate-800 dark:border-slate-700 p-4">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">Risk reduction</h2>
              <p className="text-sm text-gray-600 dark:text-gray-300">{detail.estimated_risk_reduction || '—'}</p>
            </div>

            {detail.status === 'proposed' && (
              <div className="rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/20 p-4 space-y-3">
                <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Record your decision</h2>
                <p className="text-xs text-gray-600 dark:text-gray-400">
                  Jarvis learns from your choices. No remediation is executed automatically.
                </p>
                <textarea
                  value={decisionNote}
                  onChange={(e) => setDecisionNote(e.target.value)}
                  placeholder={detail.actions?.[0]?.title || 'Notes about this decision…'}
                  rows={2}
                  className="w-full rounded border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-3 py-2 text-sm"
                />
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={recording}
                    onClick={() => recordDecision('approved')}
                    className="px-4 py-2 text-sm bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50"
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    disabled={recording}
                    onClick={() => recordDecision('rejected')}
                    className="px-4 py-2 text-sm bg-red-600 text-white rounded-md hover:bg-red-700 disabled:opacity-50"
                  >
                    Reject
                  </button>
                  <button
                    type="button"
                    disabled={recording}
                    onClick={() => recordDecision('deferred')}
                    className="px-4 py-2 text-sm bg-gray-500 text-white rounded-md hover:bg-gray-600 disabled:opacity-50"
                  >
                    Defer
                  </button>
                </div>
              </div>
            )}

            <div className="space-y-4">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                Recommended actions ({detail.action_count || detail.actions?.length || 0})
              </h2>
              {(detail.actions || []).map((action, idx) => (
                <div
                  key={`${action.title}-${idx}`}
                  className="rounded-lg border bg-white dark:bg-slate-800 dark:border-slate-700 p-4 space-y-3"
                >
                  <h3 className="font-medium text-gray-900 dark:text-white">{action.title}</h3>
                  <p className="text-sm text-gray-600 dark:text-gray-300">{action.description}</p>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                    <div>
                      <span className="text-xs uppercase text-gray-500">Impact</span>
                      <p className="text-gray-700 dark:text-gray-200">{action.impact}</p>
                    </div>
                    <div>
                      <span className="text-xs uppercase text-gray-500">Risk</span>
                      <p className="text-gray-700 dark:text-gray-200">{action.risk}</p>
                    </div>
                  </div>
                  {action.manual_steps?.length > 0 && (
                    <div>
                      <span className="text-xs uppercase text-gray-500">Manual steps</span>
                      <ol className="mt-1 list-decimal list-inside text-sm text-gray-600 dark:text-gray-300 space-y-1">
                        {action.manual_steps.map((step, stepIdx) => (
                          <li key={stepIdx}>{step}</li>
                        ))}
                      </ol>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
