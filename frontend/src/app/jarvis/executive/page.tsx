'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import Badge from '@/components/ui/Badge';
import { generateJarvisActionPlan, getJarvisExecutiveDashboard, JarvisExecutiveDashboard } from '@/lib/api';

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function formatUsd(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—';
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
      <dt className="text-xs uppercase text-gray-500 dark:text-gray-400">{label}</dt>
      <dd className="mt-1 text-xl font-semibold tabular-nums text-gray-900 dark:text-white">{value}</dd>
    </div>
  );
}

function TrendBars({
  data,
  valueKey,
  label,
  color,
}: {
  data: { date: string | null; [key: string]: string | number | null }[];
  valueKey: string;
  label: string;
  color: string;
}) {
  if (!data.length) {
    return <p className="text-sm text-gray-500">No trend data yet.</p>;
  }
  const values = data.map((d) => Number(d[valueKey]) || 0);
  const max = Math.max(...values, 1);
  return (
    <div>
      <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{label}</p>
      <div className="flex items-end gap-1 h-24">
        {data.map((point) => {
          const val = Number(point[valueKey]) || 0;
          const height = Math.max(4, (val / max) * 100);
          return (
            <div
              key={String(point.date)}
              className="flex-1 min-w-0 group relative"
              title={`${point.date}: ${val}`}
            >
              <div
                className={`w-full rounded-t ${color}`}
                style={{ height: `${height}%` }}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function statusVariant(status: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (status === 'pass') return 'success';
  if (status === 'critical' || status === 'mismatch') return 'danger';
  if (status === 'unknown') return 'warning';
  return 'neutral';
}

export default function JarvisExecutivePage() {
  const router = useRouter();
  const [data, setData] = useState<JarvisExecutiveDashboard | null>(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const dashboard = await getJarvisExecutiveDashboard();
      setData(dashboard);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load executive dashboard');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleGeneratePlan = async () => {
    setGenerating(true);
    try {
      const plan = await generateJarvisActionPlan({
        source_type: 'executive_dashboard',
        source_id: 'current',
      });
      router.push(`/jarvis/action-plans/${plan.plan_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate action plan');
    } finally {
      setGenerating(false);
    }
  };

  const infra = data?.infrastructure;
  const security = data?.security;
  const activity = data?.jarvis_activity;
  const crypto = data?.crypto_health;
  const trends = data?.trends;
  const decisions = data?.decision_intelligence;
  const execution = data?.execution;
  const followups = data?.followups;
  const objectives = data?.strategic_objectives;

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <div className="container mx-auto p-4 md:p-8 max-w-7xl">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Executive Dashboard</h1>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              Platform health overview — read-only, no autonomous execution.
            </p>
          </div>
          <div className="flex gap-3">
            <Link
              href="/jarvis"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              ← Jarvis Tasks
            </Link>
            <Link
              href="/jarvis/initiatives"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Initiatives
            </Link>
            <Link
              href="/jarvis/decisions"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Decisions
            </Link>
            <Link
              href="/jarvis/objectives"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Objectives
            </Link>
            <Link
              href="/jarvis/followups"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Follow-ups
            </Link>
            <Link
              href="/jarvis/executive-reports"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Weekly Reports
            </Link>
            <Link
              href="/jarvis/crypto-audits"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Crypto Audits
            </Link>
            <button
              type="button"
              onClick={handleGeneratePlan}
              disabled={generating || loading}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
            >
              {generating ? 'Generating…' : 'Generate action plan'}
            </button>
            <button
              type="button"
              onClick={load}
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

        {loading && !data ? (
          <div className="text-center py-8 text-gray-500">Loading executive dashboard…</div>
        ) : data ? (
          <div className="space-y-8">
            <section>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Infrastructure</h2>
              <dl className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
                <MetricCard label="AWS monthly spend" value={formatUsd(infra?.aws_monthly_spend)} />
                <MetricCard label="AWS daily spend" value={formatUsd(infra?.aws_daily_spend)} />
                <MetricCard label="EC2 instances" value={infra?.ec2_instances ?? 0} />
                <MetricCard label="EBS volumes" value={infra?.ebs_volumes ?? 0} />
                <MetricCard label="Snapshots" value={infra?.snapshots ?? 0} />
                <MetricCard label="Elastic IPs" value={infra?.elastic_ips ?? 0} />
                <MetricCard label="Last AWS audit" value={formatTimestamp(infra?.last_aws_audit_date)} />
              </dl>
            </section>

            <section>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Security</h2>
              <dl className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <MetricCard label="Open findings" value={security?.open_findings ?? 0} />
                <MetricCard label="Critical findings" value={security?.critical_findings ?? 0} />
                <MetricCard label="SGs exposed 0.0.0.0/0" value={security?.security_groups_exposed_0_0_0_0 ?? 0} />
                <MetricCard label="Untagged resources" value={security?.untagged_resources ?? 0} />
              </dl>
            </section>

            <section>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Jarvis Activity</h2>
              <dl className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                <MetricCard label="Tasks executed" value={activity?.total_tasks_executed ?? 0} />
                <MetricCard label="Audits executed" value={activity?.total_audits_executed ?? 0} />
                <MetricCard label="Success rate" value={`${activity?.success_rate ?? 0}%`} />
                <MetricCard label="Failed tasks" value={activity?.failed_tasks ?? 0} />
                <MetricCard label="Avg task cost" value={formatUsd(activity?.average_task_cost)} />
                <MetricCard label="Total Bedrock cost" value={formatUsd(activity?.total_bedrock_cost)} />
              </dl>
            </section>

            <section>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Crypto Health</h2>
              <div className="flex flex-wrap items-center gap-2 mb-3">
                <Badge variant={statusVariant(String(crypto?.reconciliation_status || 'unknown'))}>
                  {crypto?.reconciliation_status || 'unknown'}
                </Badge>
                <Badge variant="neutral">read-only</Badge>
              </div>
              <dl className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <MetricCard label="Last reconciliation" value={formatTimestamp(crypto?.last_reconciliation_date)} />
                <MetricCard label="Dashboard value" value={formatUsd(crypto?.dashboard_portfolio_value)} />
                <MetricCard label="Exchange value" value={formatUsd(crypto?.exchange_portfolio_value)} />
                <MetricCard label="Difference %" value={`${crypto?.difference_pct ?? 0}%`} />
              </dl>
            </section>

            <section>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Execution</h2>
                <Link href="/jarvis/initiatives" className="text-sm text-blue-600 dark:text-blue-400 hover:underline">
                  View all initiatives →
                </Link>
              </div>
              <dl className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                <MetricCard label="Active initiatives" value={execution?.active_initiatives ?? 0} />
                <MetricCard label="Blocked initiatives" value={execution?.blocked_initiatives ?? 0} />
                <MetricCard label="Overdue initiatives" value={execution?.overdue_initiatives ?? 0} />
                <MetricCard label="Completed this month" value={execution?.completed_this_month ?? 0} />
              </dl>
              {execution?.top_risk && (
                <div className="rounded-lg border border-orange-200 dark:border-orange-800 bg-orange-50 dark:bg-orange-950/20 p-3 text-sm">
                  <p className="text-xs uppercase text-orange-600 dark:text-orange-400">Top risk</p>
                  <p className="mt-1 text-orange-900 dark:text-orange-200">{execution.top_risk}</p>
                </div>
              )}
            </section>

            <section>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Strategic Objectives</h2>
                <Link href="/jarvis/objectives" className="text-sm text-blue-600 dark:text-blue-400 hover:underline">
                  View all objectives →
                </Link>
              </div>
              <dl className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <MetricCard label="On track" value={objectives?.objectives_on_track ?? 0} />
                <MetricCard label="At risk" value={objectives?.objectives_at_risk ?? 0} />
                <MetricCard label="Completed" value={objectives?.objectives_completed ?? 0} />
                <MetricCard label="Avg progress" value={`${objectives?.average_progress_pct ?? 0}%`} />
              </dl>
            </section>

            <section>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Follow-ups</h2>
                <Link href="/jarvis/followups" className="text-sm text-blue-600 dark:text-blue-400 hover:underline">
                  View all follow-ups →
                </Link>
              </div>
              <dl className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
                <MetricCard label="Open follow-ups" value={followups?.open_followups ?? 0} />
                <MetricCard label="Critical" value={followups?.critical_followups ?? 0} />
                <MetricCard label="Overdue" value={followups?.overdue_followups ?? 0} />
                <MetricCard label="Acknowledged" value={followups?.acknowledged_followups ?? 0} />
                <MetricCard label="Resolved this week" value={followups?.resolved_this_week ?? 0} />
              </dl>
            </section>

            <section>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Decision Intelligence</h2>
                <Link href="/jarvis/decisions" className="text-sm text-blue-600 dark:text-blue-400 hover:underline">
                  View all decisions →
                </Link>
              </div>
              <dl className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
                <MetricCard label="Success rate" value={`${decisions?.decision_success_rate ?? 0}%`} />
                <MetricCard label="Approved" value={decisions?.approved_count ?? 0} />
                <MetricCard label="Rejected" value={decisions?.rejected_count ?? 0} />
                <MetricCard label="Deferred" value={decisions?.deferred_count ?? 0} />
                <MetricCard label="Successful outcomes" value={decisions?.successful_outcomes ?? 0} />
                <MetricCard label="Repeated findings" value={decisions?.repeated_findings_count ?? 0} />
              </dl>
              {(decisions?.most_common_rejected_recommendation || decisions?.most_successful_recommendation_type) && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                  {decisions?.most_common_rejected_recommendation && (
                    <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/20 p-3">
                      <p className="text-xs uppercase text-red-600 dark:text-red-400">Most rejected recommendation</p>
                      <p className="mt-1 text-red-900 dark:text-red-200">{decisions.most_common_rejected_recommendation}</p>
                    </div>
                  )}
                  {decisions?.most_successful_recommendation_type && (
                    <div className="rounded-lg border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950/20 p-3">
                      <p className="text-xs uppercase text-green-600 dark:text-green-400">Most successful type</p>
                      <p className="mt-1 text-green-900 dark:text-green-200">{decisions.most_successful_recommendation_type}</p>
                    </div>
                  )}
                </div>
              )}
            </section>

            <section>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Trend Charts</h2>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                <TrendBars
                  data={trends?.aws_spend || []}
                  valueKey="daily"
                  label="AWS spend trend (daily)"
                  color="bg-blue-500"
                />
                <TrendBars
                  data={trends?.findings || []}
                  valueKey="open"
                  label="Findings trend (open)"
                  color="bg-orange-500"
                />
                <TrendBars
                  data={trends?.task_volume || []}
                  valueKey="tasks"
                  label="Task volume trend"
                  color="bg-green-500"
                />
              </div>
            </section>
          </div>
        ) : null}
      </div>
    </div>
  );
}
