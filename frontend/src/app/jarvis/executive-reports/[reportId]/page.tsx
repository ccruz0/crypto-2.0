'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import Badge from '@/components/ui/Badge';
import { getJarvisExecutiveReport, JarvisExecutiveReportDetail } from '@/lib/api';

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function healthVariant(score: number): 'success' | 'danger' | 'warning' | 'neutral' {
  if (score >= 80) return 'success';
  if (score >= 60) return 'warning';
  return 'danger';
}

function PriorityCard({
  item,
  showRank,
}: {
  item: {
    priority?: number;
    title: string;
    reason: string;
    expected_impact: string;
    estimated_savings_usd: number;
    risk_if_ignored: string;
  };
  showRank?: boolean;
}) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
      <div className="flex items-start gap-3">
        {showRank && item.priority != null && (
          <span className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 flex items-center justify-center text-sm font-bold">
            {item.priority}
          </span>
        )}
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-gray-900 dark:text-white">{item.title}</h3>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">{item.reason}</p>
          <dl className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-2 text-xs">
            <div>
              <dt className="uppercase text-gray-500 dark:text-gray-400">Expected impact</dt>
              <dd className="text-gray-800 dark:text-gray-200 mt-0.5">{item.expected_impact}</dd>
            </div>
            <div>
              <dt className="uppercase text-gray-500 dark:text-gray-400">Est. savings</dt>
              <dd className="text-gray-800 dark:text-gray-200 mt-0.5 tabular-nums font-mono">
                ${item.estimated_savings_usd.toFixed(2)}/mo
              </dd>
            </div>
            <div>
              <dt className="uppercase text-gray-500 dark:text-gray-400">Risk if ignored</dt>
              <dd className="text-gray-800 dark:text-gray-200 mt-0.5">{item.risk_if_ignored}</dd>
            </div>
          </dl>
        </div>
      </div>
    </div>
  );
}

export default function JarvisExecutiveReportDetailPage() {
  const params = useParams();
  const reportId = typeof params.reportId === 'string' ? params.reportId : '';
  const [detail, setDetail] = useState<JarvisExecutiveReportDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDetail = useCallback(async () => {
    if (!reportId) return;
    setLoading(true);
    try {
      const data = await getJarvisExecutiveReport(reportId);
      setDetail(data);
      setError(null);
    } catch (err) {
      setDetail(null);
      setError(err instanceof Error ? err.message : 'Failed to load executive report');
    } finally {
      setLoading(false);
    }
  }, [reportId]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <div className="container mx-auto p-4 md:p-8 max-w-7xl">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Executive Report</h1>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1 font-mono">{reportId}</p>
          </div>
          <div className="flex gap-3">
            <Link
              href="/jarvis/executive-reports"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              ← All Reports
            </Link>
            <button
              type="button"
              onClick={loadDetail}
              disabled={loading}
              className="px-4 py-2 text-sm bg-gray-200 dark:bg-slate-700 rounded-md hover:bg-gray-300 dark:hover:bg-slate-600 disabled:opacity-50"
            >
              {loading ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-300 bg-red-50 dark:bg-red-950/30 text-red-800 dark:text-red-200 px-4 py-3 text-sm">
            {error}
          </div>
        )}

        {loading && !detail ? (
          <div className="text-center py-8 text-gray-500">Loading report…</div>
        ) : detail ? (
          <div className="space-y-8">
            <section className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-6">
              <div className="flex flex-wrap items-center gap-4">
                <div>
                  <p className="text-xs uppercase text-gray-500 dark:text-gray-400">Health Score</p>
                  <p className="text-5xl font-bold tabular-nums text-gray-900 dark:text-white">
                    {detail.overall_health_score}
                  </p>
                </div>
                <Badge variant={healthVariant(detail.overall_health_score)}>
                  {detail.overall_health_score >= 80 ? 'healthy' : detail.overall_health_score >= 60 ? 'attention' : 'critical'}
                </Badge>
                <div>
                  <p className="text-xs uppercase text-gray-500 dark:text-gray-400">Generated</p>
                  <p className="text-sm text-gray-700 dark:text-gray-300">{formatTimestamp(detail.generated_at)}</p>
                </div>
                <Badge variant="neutral">read-only</Badge>
                <Badge variant="neutral">no execution</Badge>
              </div>
            </section>

            <section>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Top Priorities</h2>
              {detail.top_priorities.length === 0 ? (
                <p className="text-sm text-gray-500">No priorities identified.</p>
              ) : (
                <div className="space-y-3">
                  {detail.top_priorities.map((item) => (
                    <PriorityCard key={`${item.priority}-${item.title}`} item={item} showRank />
                  ))}
                </div>
              )}
            </section>

            {detail.quick_wins.length > 0 && (
              <section>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Quick Wins</h2>
                <div className="space-y-3">
                  {detail.quick_wins.map((item) => (
                    <PriorityCard key={item.title} item={item} />
                  ))}
                </div>
              </section>
            )}

            {detail.strategic_items.length > 0 && (
              <section>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Strategic Items</h2>
                <div className="space-y-3">
                  {detail.strategic_items.map((item) => (
                    <PriorityCard key={item.title} item={item} />
                  ))}
                </div>
              </section>
            )}

            {detail.strategic_alignment && (detail.strategic_alignment.objectives?.length ?? 0) > 0 && (
              <section>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Strategic Alignment</h2>
                <div className="space-y-3">
                  {(detail.strategic_alignment.objectives || []).map((obj) => (
                    <div
                      key={obj.objective_id}
                      className="rounded-lg border border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-950/20 p-4"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <Link
                          href={`/jarvis/objectives/${obj.objective_id}`}
                          className="font-semibold text-indigo-900 dark:text-indigo-200 hover:underline"
                        >
                          {obj.title}
                        </Link>
                        <Badge variant={obj.status === 'On track' ? 'success' : obj.status === 'At risk' ? 'danger' : 'warning'}>
                          {obj.status}
                        </Badge>
                      </div>
                      <dl className="mt-3 grid grid-cols-2 md:grid-cols-3 gap-2 text-sm">
                        <div>
                          <dt className="text-xs uppercase text-indigo-600 dark:text-indigo-400">Progress</dt>
                          <dd className="tabular-nums font-medium">{obj.progress_pct}%</dd>
                        </div>
                        <div>
                          <dt className="text-xs uppercase text-indigo-600 dark:text-indigo-400">Supporting initiatives</dt>
                          <dd className="tabular-nums font-medium">{obj.supporting_initiatives}</dd>
                        </div>
                        <div>
                          <dt className="text-xs uppercase text-indigo-600 dark:text-indigo-400">Health</dt>
                          <dd className="font-medium">{obj.health}</dd>
                        </div>
                      </dl>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {detail.followup_review && (detail.followup_review.top_followups?.length ?? 0) > 0 && (
              <section>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Follow-up Review</h2>
                <dl className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                  <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                    <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Open</dt>
                    <dd className="mt-1 text-xl font-semibold tabular-nums">
                      {detail.followup_review.summary?.open_followups ?? 0}
                    </dd>
                  </div>
                  <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                    <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Critical</dt>
                    <dd className="mt-1 text-xl font-semibold tabular-nums">
                      {detail.followup_review.summary?.critical_followups ?? 0}
                    </dd>
                  </div>
                  <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                    <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Overdue</dt>
                    <dd className="mt-1 text-xl font-semibold tabular-nums">
                      {detail.followup_review.summary?.overdue_followups ?? 0}
                    </dd>
                  </div>
                  <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                    <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">High severity</dt>
                    <dd className="mt-1 text-xl font-semibold tabular-nums">
                      {detail.followup_review.summary?.high_followups ?? 0}
                    </dd>
                  </div>
                </dl>
                <div className="space-y-2">
                  {(detail.followup_review.top_followups || []).map((item) => (
                    <div
                      key={item.followup_id}
                      className="rounded-lg border border-purple-200 dark:border-purple-800 bg-purple-50 dark:bg-purple-950/20 p-3 text-sm"
                    >
                      <div className="flex items-center gap-2">
                        <Badge variant={item.severity === 'critical' ? 'danger' : item.severity === 'high' ? 'warning' : 'neutral'}>
                          {item.severity}
                        </Badge>
                        <Link
                          href={`/jarvis/followups/${item.followup_id}`}
                          className="font-medium text-purple-900 dark:text-purple-200 hover:underline"
                        >
                          {item.title}
                        </Link>
                      </div>
                      <p className="text-xs text-purple-700 dark:text-purple-400 mt-1">
                        Reminders: {item.reminder_count}
                        {item.is_overdue ? ' · overdue' : ''}
                      </p>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {detail.execution_review && (
              <section>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Execution Review</h2>
                <dl className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                  <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                    <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Active</dt>
                    <dd className="mt-1 text-xl font-semibold tabular-nums">{detail.execution_review.active}</dd>
                  </div>
                  <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                    <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Blocked</dt>
                    <dd className="mt-1 text-xl font-semibold tabular-nums">{detail.execution_review.blocked}</dd>
                  </div>
                  <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                    <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Overdue</dt>
                    <dd className="mt-1 text-xl font-semibold tabular-nums">{detail.execution_review.overdue}</dd>
                  </div>
                  <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                    <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">Stalled</dt>
                    <dd className="mt-1 text-xl font-semibold tabular-nums">{detail.execution_review.stalled}</dd>
                  </div>
                </dl>
                {detail.execution_review.top_risk && (
                  <div className="rounded-lg border border-orange-200 dark:border-orange-800 bg-orange-50 dark:bg-orange-950/20 p-4">
                    <p className="text-xs uppercase text-orange-600 dark:text-orange-400">Top Risk</p>
                    <p className="mt-1 text-sm text-orange-900 dark:text-orange-200">{detail.execution_review.top_risk}</p>
                  </div>
                )}
              </section>
            )}

            {(detail.lessons_learned?.length ?? 0) > 0 && (
              <section>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Lessons Learned</h2>
                <ul className="space-y-2">
                  {(detail.lessons_learned || []).map((lesson) => (
                    <li
                      key={lesson}
                      className="rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/20 p-3 text-sm text-blue-900 dark:text-blue-200"
                    >
                      {lesson}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {detail.blocked_items.length > 0 && (
              <section>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Blocked Items</h2>
                <div className="space-y-3">
                  {detail.blocked_items.map((item) => (
                    <div
                      key={item.title}
                      className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/20 p-4"
                    >
                      <h3 className="font-semibold text-amber-900 dark:text-amber-200">{item.title}</h3>
                      <p className="text-sm text-amber-800 dark:text-amber-300 mt-1">{item.reason}</p>
                      <p className="text-xs text-amber-700 dark:text-amber-400 mt-2">
                        Blocked by: {item.blocked_by}
                      </p>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
