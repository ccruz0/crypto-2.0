'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import Badge from '@/components/ui/Badge';
import { getJarvisObjective, JarvisObjectiveDetail } from '@/lib/api';

function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString();
}

function healthVariant(health: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (health === 'green') return 'success';
  if (health === 'red') return 'danger';
  if (health === 'yellow') return 'warning';
  return 'neutral';
}

function krStatusVariant(status: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (status === 'achieved' || status === 'on_track') return 'success';
  if (status === 'behind') return 'danger';
  if (status === 'at_risk') return 'warning';
  return 'neutral';
}

function TrendBars({ data }: { data: { date: string | null; progress_pct: number }[] }) {
  if (!data.length) {
    return <p className="text-sm text-gray-500">No trend data yet. Snapshots recorded on report generation.</p>;
  }
  const max = Math.max(...data.map((d) => d.progress_pct), 1);
  return (
    <div className="flex items-end gap-1 h-24">
      {data.map((point) => {
        const height = Math.max(4, (point.progress_pct / max) * 100);
        return (
          <div
            key={String(point.date)}
            className="flex-1 min-w-0 group relative"
            title={`${point.date}: ${point.progress_pct}%`}
          >
            <div className="w-full rounded-t bg-indigo-500" style={{ height: `${height}%` }} />
          </div>
        );
      })}
    </div>
  );
}

export default function JarvisObjectiveDetailPage() {
  const params = useParams();
  const objectiveId = typeof params.objectiveId === 'string' ? params.objectiveId : '';
  const [detail, setDetail] = useState<JarvisObjectiveDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDetail = useCallback(async () => {
    if (!objectiveId) return;
    setLoading(true);
    try {
      const data = await getJarvisObjective(objectiveId);
      setDetail(data);
      setError(null);
    } catch (err) {
      setDetail(null);
      setError(err instanceof Error ? err.message : 'Failed to load objective');
    } finally {
      setLoading(false);
    }
  }, [objectiveId]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <div className="container mx-auto p-4 md:p-8 max-w-7xl">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Strategic Objective</h1>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1 font-mono">{objectiveId}</p>
          </div>
          <Link
            href="/jarvis/objectives"
            className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
          >
            ← All objectives
          </Link>
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-300 bg-red-50 dark:bg-red-950/30 text-red-800 dark:text-red-200 px-4 py-3 text-sm">
            {error}
          </div>
        )}

        {loading && !detail ? (
          <div className="text-center py-8 text-gray-500">Loading objective…</div>
        ) : detail ? (
          <div className="space-y-6">
            <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-6">
              <div className="flex flex-wrap items-center gap-2 mb-4">
                <Badge variant={healthVariant(detail.health)}>{detail.health}</Badge>
                <Badge variant="neutral">{detail.status}</Badge>
                <Badge variant="neutral">{detail.alignment_status}</Badge>
                <Badge variant="neutral">read-only</Badge>
                {detail.is_overdue && <Badge variant="danger">overdue</Badge>}
              </div>

              <h2 className="text-xl font-semibold text-gray-900 dark:text-white">{detail.title}</h2>
              {detail.description && (
                <p className="mt-2 text-gray-600 dark:text-gray-400">{detail.description}</p>
              )}

              <dl className="mt-6 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div>
                  <dt className="text-xs uppercase text-gray-500">Progress</dt>
                  <dd className="mt-1 text-2xl font-semibold tabular-nums">{detail.progress_pct}%</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-gray-500">Owner</dt>
                  <dd className="mt-1">{detail.owner || '—'}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-gray-500">Target date</dt>
                  <dd className="mt-1">{formatDate(detail.target_date)}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-gray-500">Key results</dt>
                  <dd className="mt-1 tabular-nums">{detail.key_results?.length ?? 0}</dd>
                </div>
              </dl>
            </div>

            <section>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Key Results</h3>
              {detail.key_results?.length ? (
                <div className="space-y-3">
                  {detail.key_results.map((kr) => (
                    <div
                      key={kr.kr_id}
                      className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4"
                    >
                      <div className="flex flex-wrap items-center gap-2 mb-2">
                        <Badge variant={krStatusVariant(kr.status)}>{kr.status.replace('_', ' ')}</Badge>
                        <span className="text-sm text-gray-500 tabular-nums">{kr.progress_pct}%</span>
                      </div>
                      <p className="font-medium text-gray-900 dark:text-white">{kr.title}</p>
                      {kr.metric_name && (
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 font-mono">
                          metric: {kr.metric_name}
                        </p>
                      )}
                      <p className="text-sm text-gray-600 dark:text-gray-400 mt-1 tabular-nums">
                        Current: {kr.current_value}{kr.unit ? ` ${kr.unit}` : ''} → Target: {kr.target_value}
                        {kr.unit ? ` ${kr.unit}` : ''}
                      </p>
                      {(kr.metric_source || kr.last_refreshed_at) && (
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                          {kr.metric_source && <>Source: {kr.metric_source}</>}
                          {kr.metric_source && kr.last_refreshed_at && ' · '}
                          {kr.last_refreshed_at && <>Last refreshed: {formatDate(kr.last_refreshed_at)}</>}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-500">No key results defined.</p>
              )}
            </section>

            <section>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Linked Initiatives</h3>
              {detail.linked_initiatives?.length ? (
                <ul className="space-y-2">
                  {detail.linked_initiatives.map((init) => {
                    const id = String(init.initiative_id || '');
                    const title = String(init.title || id);
                    return (
                      <li key={id}>
                        <Link
                          href={`/jarvis/initiatives/${id}`}
                          className="text-blue-600 dark:text-blue-400 hover:underline text-sm"
                        >
                          {title}
                        </Link>
                        <span className="ml-2 text-xs text-gray-500">
                          {String(init.status)} · {String(init.progress_pct ?? 0)}%
                        </span>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="text-sm text-gray-500">No linked initiatives.</p>
              )}
            </section>

            <section>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Progress Trend</h3>
              <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                <TrendBars data={detail.progress_trend || []} />
              </div>
            </section>

            {detail.risks?.length > 0 && (
              <section>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Risks</h3>
                <ul className="space-y-2">
                  {detail.risks.map((risk) => (
                    <li
                      key={risk}
                      className="rounded-lg border border-orange-200 dark:border-orange-800 bg-orange-50 dark:bg-orange-950/20 p-3 text-sm text-orange-900 dark:text-orange-200"
                    >
                      {risk}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
