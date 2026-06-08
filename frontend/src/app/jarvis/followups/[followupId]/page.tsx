'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import Badge from '@/components/ui/Badge';
import {
  getJarvisFollowup,
  JarvisFollowupDetail,
  JarvisFollowupStatus,
  updateJarvisFollowup,
} from '@/lib/api';

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

function severityVariant(severity: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (severity === 'critical') return 'danger';
  if (severity === 'high') return 'warning';
  if (severity === 'low') return 'success';
  return 'neutral';
}

function statusVariant(status: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (status === 'resolved') return 'success';
  if (status === 'dismissed') return 'neutral';
  if (status === 'acknowledged') return 'warning';
  return 'danger';
}

function sourceHref(detail: JarvisFollowupDetail): string | null {
  if (!detail.source_type || !detail.source_id) return null;
  if (detail.source_type === 'initiative') return `/jarvis/initiatives/${detail.source_id}`;
  if (detail.source_type === 'action_plan') return `/jarvis/action-plans/${detail.source_id}`;
  if (detail.source_type === 'decision') return `/jarvis/decisions/${detail.source_id}`;
  if (detail.source_type === 'aws_audit') return `/jarvis/audits/${detail.source_id}`;
  if (detail.source_type === 'crypto_audit') return `/jarvis/crypto-audits/${detail.source_id}`;
  return null;
}

export default function JarvisFollowupDetailPage() {
  const params = useParams();
  const followupId = typeof params.followupId === 'string' ? params.followupId : '';
  const [detail, setDetail] = useState<JarvisFollowupDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDetail = useCallback(async () => {
    if (!followupId) return;
    setLoading(true);
    try {
      const data = await getJarvisFollowup(followupId);
      setDetail(data);
      setError(null);
    } catch (err) {
      setDetail(null);
      setError(err instanceof Error ? err.message : 'Failed to load follow-up');
    } finally {
      setLoading(false);
    }
  }, [followupId]);

  const handleStatusUpdate = useCallback(
    async (status: JarvisFollowupStatus) => {
      if (!followupId) return;
      setUpdating(true);
      try {
        const updated = await updateJarvisFollowup(followupId, { status });
        setDetail(updated);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to update follow-up');
      } finally {
        setUpdating(false);
      }
    },
    [followupId],
  );

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  const linkedHref = detail ? sourceHref(detail) : null;

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <div className="container mx-auto p-4 md:p-8 max-w-7xl">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Follow-up</h1>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1 font-mono">{followupId}</p>
          </div>
          <Link
            href="/jarvis/followups"
            className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
          >
            ← All follow-ups
          </Link>
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-300 bg-red-50 dark:bg-red-950/30 text-red-800 dark:text-red-200 px-4 py-3 text-sm">
            {error}
          </div>
        )}

        {loading && !detail ? (
          <div className="text-center py-8 text-gray-500">Loading follow-up…</div>
        ) : detail ? (
          <div className="space-y-6">
            <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-6">
              <div className="flex flex-wrap items-center gap-2 mb-4">
                <Badge variant={severityVariant(detail.severity)}>{detail.severity}</Badge>
                <Badge variant={statusVariant(detail.status)}>{detail.status}</Badge>
                <Badge variant="neutral">read-only</Badge>
                {detail.is_overdue && <Badge variant="danger">overdue</Badge>}
              </div>

              <h2 className="text-xl font-semibold text-gray-900 dark:text-white">{detail.title}</h2>
              {detail.description && (
                <p className="mt-2 text-gray-600 dark:text-gray-400">{detail.description}</p>
              )}

              <dl className="mt-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 text-sm">
                <div>
                  <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Source</dt>
                  <dd className="mt-1 text-gray-900 dark:text-white capitalize">
                    {detail.source_type.replace(/_/g, ' ')}
                    {linkedHref ? (
                      <>
                        {' — '}
                        <Link href={linkedHref} className="text-blue-600 dark:text-blue-400 hover:underline">
                          view source
                        </Link>
                      </>
                    ) : detail.source_id ? (
                      <span className="font-mono text-xs ml-1">{detail.source_id}</span>
                    ) : null}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Due date</dt>
                  <dd className="mt-1 text-gray-900 dark:text-white">{formatDate(detail.due_date)}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Assigned to</dt>
                  <dd className="mt-1 text-gray-900 dark:text-white">{detail.assigned_to || '—'}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Reminder count</dt>
                  <dd className="mt-1 text-gray-900 dark:text-white tabular-nums">{detail.reminder_count}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Last reminded</dt>
                  <dd className="mt-1 text-gray-900 dark:text-white">{formatTimestamp(detail.last_reminded_at)}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Updated</dt>
                  <dd className="mt-1 text-gray-900 dark:text-white">{formatTimestamp(detail.updated_at)}</dd>
                </div>
              </dl>
            </div>

            <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
                Update status (human-controlled — no execution performed):
              </p>
              <div className="flex flex-wrap gap-2">
                {(['acknowledged', 'resolved', 'dismissed'] as JarvisFollowupStatus[]).map((status) => (
                  <button
                    key={status}
                    type="button"
                    disabled={updating || detail.status === status}
                    onClick={() => handleStatusUpdate(status)}
                    className="px-3 py-1.5 text-sm border border-gray-300 dark:border-slate-600 rounded-md hover:bg-gray-100 dark:hover:bg-slate-700 disabled:opacity-50 capitalize"
                  >
                    {status}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
