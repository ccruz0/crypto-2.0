'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import Badge from '@/components/ui/Badge';
import { getJarvisDecision, JarvisDecisionDetail } from '@/lib/api';

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function decisionVariant(decision: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (decision === 'approved') return 'success';
  if (decision === 'rejected') return 'danger';
  return 'warning';
}

function outcomeVariant(outcome: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (outcome === 'successful') return 'success';
  if (outcome === 'unsuccessful') return 'danger';
  if (outcome === 'partial') return 'warning';
  return 'neutral';
}

export default function JarvisDecisionDetailPage() {
  const params = useParams();
  const decisionId = typeof params.decisionId === 'string' ? params.decisionId : '';
  const [detail, setDetail] = useState<JarvisDecisionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDetail = useCallback(async () => {
    if (!decisionId) return;
    setLoading(true);
    try {
      const data = await getJarvisDecision(decisionId);
      setDetail(data);
      setError(null);
    } catch (err) {
      setDetail(null);
      setError(err instanceof Error ? err.message : 'Failed to load decision');
    } finally {
      setLoading(false);
    }
  }, [decisionId]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  const planHref = detail?.plan_id ? `/jarvis/action-plans/${detail.plan_id}` : null;
  const sourceHref =
    detail?.source_type === 'aws_audit' && detail.source_id
      ? `/jarvis/audits/${detail.source_id}`
      : detail?.source_type === 'crypto_audit' && detail.source_id
        ? `/jarvis/crypto-audits/${detail.source_id}`
        : null;

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <div className="container mx-auto p-4 md:p-8 max-w-7xl">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Decision Record</h1>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1 font-mono">{decisionId}</p>
          </div>
          <Link
            href="/jarvis/decisions"
            className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
          >
            ← All decisions
          </Link>
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-300 bg-red-50 dark:bg-red-950/30 text-red-800 dark:text-red-200 px-4 py-3 text-sm">
            {error}
          </div>
        )}

        {loading && !detail ? (
          <p className="text-sm text-gray-500">Loading decision…</p>
        ) : detail ? (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="rounded-lg border bg-white dark:bg-slate-800 dark:border-slate-700 p-4">
                <p className="text-xs text-gray-500 uppercase">Decision</p>
                <div className="mt-2">
                  <Badge variant={decisionVariant(detail.decision)}>{detail.decision}</Badge>
                </div>
              </div>
              <div className="rounded-lg border bg-white dark:bg-slate-800 dark:border-slate-700 p-4">
                <p className="text-xs text-gray-500 uppercase">Outcome</p>
                <div className="mt-2">
                  <Badge variant={outcomeVariant(detail.outcome)}>{detail.outcome}</Badge>
                </div>
              </div>
              <div className="rounded-lg border bg-white dark:bg-slate-800 dark:border-slate-700 p-4">
                <p className="text-xs text-gray-500 uppercase">Created</p>
                <p className="mt-2 text-sm">{formatTimestamp(detail.created_at)}</p>
              </div>
              <div className="rounded-lg border bg-white dark:bg-slate-800 dark:border-slate-700 p-4">
                <p className="text-xs text-gray-500 uppercase">Reviewed by</p>
                <p className="mt-2 text-sm">{detail.reviewed_by || '—'}</p>
              </div>
            </div>

            <div className="rounded-lg border bg-white dark:bg-slate-800 dark:border-slate-700 p-4">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">Notes</h2>
              <p className="text-sm text-gray-600 dark:text-gray-300 whitespace-pre-wrap">
                {detail.decision_reason || '—'}
              </p>
            </div>

            <div className="rounded-lg border bg-white dark:bg-slate-800 dark:border-slate-700 p-4 space-y-2">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Source</h2>
              <p className="text-sm text-gray-600 dark:text-gray-300">
                Type: <span className="font-mono">{detail.source_type || '—'}</span>
              </p>
              {sourceHref ? (
                <Link href={sourceHref} className="text-sm text-blue-600 dark:text-blue-400 hover:underline">
                  View source audit ({detail.source_id})
                </Link>
              ) : (
                <p className="text-sm font-mono text-gray-500">{detail.source_id || '—'}</p>
              )}
              {planHref && (
                <Link href={planHref} className="text-sm text-blue-600 dark:text-blue-400 hover:underline block">
                  View action plan ({detail.plan_id})
                </Link>
              )}
            </div>

            {detail.reviewed_at && (
              <div className="rounded-lg border bg-white dark:bg-slate-800 dark:border-slate-700 p-4">
                <h2 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">Review</h2>
                <p className="text-sm text-gray-600 dark:text-gray-300">
                  Reviewed at: {formatTimestamp(detail.reviewed_at)}
                </p>
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
