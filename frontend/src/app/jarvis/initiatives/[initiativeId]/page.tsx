'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import Badge from '@/components/ui/Badge';
import { getJarvisInitiative, JarvisInitiativeDetail } from '@/lib/api';

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString();
}

function statusVariant(status: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (status === 'completed') return 'success';
  if (status === 'blocked' || status === 'cancelled') return 'danger';
  if (status === 'active') return 'warning';
  return 'neutral';
}

function priorityVariant(priority: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (priority === 'critical') return 'danger';
  if (priority === 'high') return 'warning';
  return 'neutral';
}

function healthVariant(health: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (health === 'green') return 'success';
  if (health === 'red') return 'danger';
  if (health === 'yellow') return 'warning';
  return 'neutral';
}

function sourceHref(detail: JarvisInitiativeDetail): string | null {
  if (!detail.source_type || !detail.source_id) return null;
  if (detail.source_type === 'aws_audit') return `/jarvis/audits/${detail.source_id}`;
  if (detail.source_type === 'crypto_audit') return `/jarvis/crypto-audits/${detail.source_id}`;
  if (detail.source_type === 'action_plan') return `/jarvis/action-plans/${detail.source_id}`;
  if (detail.source_type === 'decision') return `/jarvis/decisions/${detail.source_id}`;
  if (detail.source_type === 'executive_report') return `/jarvis/executive-reports/${detail.source_id}`;
  if (detail.source_type === 'objective') return `/jarvis/objectives/${detail.source_id}`;
  return null;
}

export default function JarvisInitiativeDetailPage() {
  const params = useParams();
  const initiativeId = typeof params.initiativeId === 'string' ? params.initiativeId : '';
  const [detail, setDetail] = useState<JarvisInitiativeDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDetail = useCallback(async () => {
    if (!initiativeId) return;
    setLoading(true);
    try {
      const data = await getJarvisInitiative(initiativeId);
      setDetail(data);
      setError(null);
    } catch (err) {
      setDetail(null);
      setError(err instanceof Error ? err.message : 'Failed to load initiative');
    } finally {
      setLoading(false);
    }
  }, [initiativeId]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  const linkedHref = detail ? sourceHref(detail) : null;

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <div className="container mx-auto p-4 md:p-8 max-w-7xl">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Initiative</h1>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1 font-mono">{initiativeId}</p>
          </div>
          <Link
            href="/jarvis/initiatives"
            className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
          >
            ← All initiatives
          </Link>
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-300 bg-red-50 dark:bg-red-950/30 text-red-800 dark:text-red-200 px-4 py-3 text-sm">
            {error}
          </div>
        )}

        {loading && !detail ? (
          <div className="text-center py-8 text-gray-500">Loading initiative…</div>
        ) : detail ? (
          <div className="space-y-6">
            <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-6">
              <div className="flex flex-wrap items-center gap-2 mb-4">
                <Badge variant={statusVariant(detail.status)}>{detail.status}</Badge>
                <Badge variant={priorityVariant(detail.priority)}>{detail.priority}</Badge>
                <Badge variant={healthVariant(detail.health)}>health: {detail.health}</Badge>
                {detail.is_overdue && <Badge variant="danger">overdue {detail.days_overdue}d</Badge>}
                {detail.is_stalled && <Badge variant="warning">stalled</Badge>}
                <Badge variant="neutral">read-only</Badge>
              </div>

              <h2 className="text-xl font-semibold text-gray-900 dark:text-white">{detail.title}</h2>
              {detail.description && (
                <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">{detail.description}</p>
              )}

              <dl className="mt-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 text-sm">
                <div>
                  <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Owner</dt>
                  <dd className="mt-1 text-gray-900 dark:text-white">{detail.owner || '—'}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Target date</dt>
                  <dd className="mt-1 text-gray-900 dark:text-white">{formatDate(detail.target_date)}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Progress</dt>
                  <dd className="mt-1 text-gray-900 dark:text-white tabular-nums font-mono">{detail.progress_pct}%</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Created</dt>
                  <dd className="mt-1 text-gray-900 dark:text-white">{formatTimestamp(detail.created_at)}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Last updated</dt>
                  <dd className="mt-1 text-gray-900 dark:text-white">{formatTimestamp(detail.updated_at)}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Source</dt>
                  <dd className="mt-1 text-gray-900 dark:text-white">
                    {detail.source_type || '—'}
                    {linkedHref ? (
                      <>
                        {' '}
                        <Link href={linkedHref} className="text-blue-600 dark:text-blue-400 hover:underline font-mono text-xs">
                          {detail.source_id?.slice(0, 8)}…
                        </Link>
                      </>
                    ) : detail.source_id ? (
                      <span className="font-mono text-xs ml-1">{detail.source_id.slice(0, 8)}…</span>
                    ) : null}
                  </dd>
                </div>
              </dl>

              {detail.blocked_reason && (
                <div className="mt-6 rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/20 p-4">
                  <p className="text-xs uppercase text-red-600 dark:text-red-400">Blocked reason</p>
                  <p className="mt-1 text-sm text-red-900 dark:text-red-200">{detail.blocked_reason}</p>
                </div>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
