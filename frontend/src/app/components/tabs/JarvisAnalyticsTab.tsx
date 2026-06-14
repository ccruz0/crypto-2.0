'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  getJarvisAnalyticsOverview,
  getJarvisAnalyticsProposals,
  getJarvisAnalyticsRootCauses,
  getJarvisAnalyticsTemplates,
  getJarvisAnalyticsTools,
  type JarvisAnalyticsOverview,
  type JarvisAnalyticsProposals,
  type JarvisAnalyticsRootCauses,
  type JarvisAnalyticsTemplateRow,
  type JarvisAnalyticsToolRow,
} from '@/app/api';

type Section = 'overview' | 'templates' | 'tools' | 'proposals' | 'root-causes';

function MetricCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
      <div className="text-xs uppercase tracking-wide text-gray-500 dark:text-slate-400">{label}</div>
      <div className="text-2xl font-bold text-gray-900 dark:text-white mt-1">{value}</div>
      {sub && <div className="text-xs text-gray-500 dark:text-slate-400 mt-1">{sub}</div>}
    </div>
  );
}

function QualityScoreBadge({ score }: { score: number }) {
  const color =
    score >= 85 ? 'text-green-600 dark:text-green-400' : score >= 70 ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400';
  return <span className={`text-3xl font-bold ${color}`}>{score.toFixed(1)}</span>;
}

function MiniBarChart({ data, valueKey, color }: { data: { date: string; [k: string]: string | number }[]; valueKey: string; color: string }) {
  const max = Math.max(1, ...data.map((d) => Number(d[valueKey] || 0)));
  return (
    <div className="flex items-end gap-0.5 h-24">
      {data.map((point) => {
        const val = Number(point[valueKey] || 0);
        const height = Math.max(4, (val / max) * 100);
        return (
          <div
            key={point.date}
            className={`flex-1 rounded-t ${color}`}
            style={{ height: `${height}%` }}
            title={`${point.date}: ${val}`}
          />
        );
      })}
    </div>
  );
}

function SortableTemplateTable({ rows }: { rows: JarvisAnalyticsTemplateRow[] }) {
  const [sortKey, setSortKey] = useState<keyof JarvisAnalyticsTemplateRow>('completion_rate_pct');
  const [sortAsc, setSortAsc] = useState(false);

  const sorted = useMemo(() => {
    return [...rows].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === 'number' && typeof bv === 'number') {
        return sortAsc ? av - bv : bv - av;
      }
      return sortAsc ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
    });
  }, [rows, sortKey, sortAsc]);

  const header = (key: keyof JarvisAnalyticsTemplateRow, label: string) => (
    <th
      className="px-3 py-2 text-left text-xs font-semibold uppercase cursor-pointer hover:text-blue-600"
      onClick={() => {
        if (sortKey === key) setSortAsc(!sortAsc);
        else {
          setSortKey(key);
          setSortAsc(false);
        }
      }}
    >
      {label}
    </th>
  );

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm" data-testid="jarvis-analytics-templates-table">
        <thead className="bg-gray-50 dark:bg-slate-900/50">
          <tr>
            {header('template_id', 'Template')}
            {header('investigations', 'Investigations')}
            {header('completion_rate_pct', 'Completion %')}
            {header('failure_rate_pct', 'Failure %')}
            {header('insufficient_evidence_rate_pct', 'Insufficient %')}
            {header('average_confidence', 'Confidence %')}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={row.template_id} className="border-t border-gray-100 dark:border-slate-700">
              <td className="px-3 py-2 font-mono text-xs">{row.template_id}</td>
              <td className="px-3 py-2">{row.investigations}</td>
              <td className="px-3 py-2">{row.completion_rate_pct.toFixed(1)}%</td>
              <td className="px-3 py-2">{row.failure_rate_pct.toFixed(1)}%</td>
              <td className="px-3 py-2">{row.insufficient_evidence_rate_pct.toFixed(1)}%</td>
              <td className="px-3 py-2">{row.average_confidence.toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ToolTable({ rows }: { rows: JarvisAnalyticsToolRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm" data-testid="jarvis-analytics-tools-table">
        <thead className="bg-gray-50 dark:bg-slate-900/50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Tool</th>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Executions</th>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Success %</th>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Failures</th>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Avg Duration</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.tool} className="border-t border-gray-100 dark:border-slate-700">
              <td className="px-3 py-2 font-mono text-xs">{row.tool}</td>
              <td className="px-3 py-2">{row.executions}</td>
              <td className="px-3 py-2">{row.success_rate_pct.toFixed(1)}%</td>
              <td className="px-3 py-2">{row.failures}</td>
              <td className="px-3 py-2">{(row.average_duration_ms / 1000).toFixed(2)}s</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ProposalFunnel({ proposals }: { proposals: JarvisAnalyticsProposals['proposals'] }) {
  const stages = [
    { key: 'proposals_generated', label: 'Generated', color: 'bg-blue-500' },
    { key: 'waiting_for_approval', label: 'Waiting', color: 'bg-amber-500' },
    { key: 'approved', label: 'Approved', color: 'bg-green-500' },
    { key: 'rejected', label: 'Rejected', color: 'bg-red-400' },
    { key: 'no_fix_required', label: 'No Fix', color: 'bg-slate-400' },
    { key: 'failed', label: 'Failed', color: 'bg-red-600' },
  ] as const;
  const max = Math.max(1, proposals.proposals_generated);

  return (
    <div className="space-y-3" data-testid="jarvis-analytics-proposal-funnel">
      {stages.map((stage) => {
        const count = Number(proposals[stage.key as keyof typeof proposals] || 0);
        const width = Math.max(8, (count / max) * 100);
        return (
          <div key={stage.key} className="flex items-center gap-3">
            <div className="w-28 text-xs text-gray-600 dark:text-slate-300">{stage.label}</div>
            <div className="flex-1 h-6 bg-gray-100 dark:bg-slate-700 rounded overflow-hidden">
              <div className={`h-full ${stage.color} flex items-center px-2 text-xs text-white font-semibold`} style={{ width: `${width}%` }}>
                {count > 0 ? count : ''}
              </div>
            </div>
          </div>
        );
      })}
      <div className="text-sm text-gray-600 dark:text-slate-300 mt-2">
        Useful proposals: {proposals.useful_proposals} ({proposals.useful_rate_pct.toFixed(1)}%)
      </div>
    </div>
  );
}

export default function JarvisAnalyticsTab() {
  const [section, setSection] = useState<Section>('overview');
  const [overview, setOverview] = useState<JarvisAnalyticsOverview | null>(null);
  const [templates, setTemplates] = useState<JarvisAnalyticsTemplateRow[]>([]);
  const [tools, setTools] = useState<JarvisAnalyticsToolRow[]>([]);
  const [proposals, setProposals] = useState<JarvisAnalyticsProposals | null>(null);
  const [rootCauses, setRootCauses] = useState<JarvisAnalyticsRootCauses | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ov, tmpl, toolRows, prop, roots] = await Promise.all([
        getJarvisAnalyticsOverview(),
        getJarvisAnalyticsTemplates(),
        getJarvisAnalyticsTools(),
        getJarvisAnalyticsProposals(),
        getJarvisAnalyticsRootCauses(),
      ]);
      setOverview(ov);
      setTemplates(tmpl.templates || []);
      setTools(toolRows.tools || []);
      setProposals(prop);
      setRootCauses(roots);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load analytics');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 30000);
    return () => clearInterval(timer);
  }, [refresh]);

  const sections: { id: Section; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'templates', label: 'Templates' },
    { id: 'tools', label: 'Tools' },
    { id: 'proposals', label: 'Proposals' },
    { id: 'root-causes', label: 'Root Causes' },
  ];

  const inv = overview?.investigations;

  return (
    <div className="space-y-4" data-testid="jarvis-analytics-tab">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">Jarvis Analytics</h2>
          <p className="text-sm text-gray-500 dark:text-slate-400">Investigation quality and reliability dashboard (read-only)</p>
        </div>
        <button
          type="button"
          onClick={refresh}
          className="px-3 py-1.5 text-sm rounded-md bg-blue-600 text-white hover:bg-blue-700"
        >
          Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-md bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 px-4 py-2 text-sm">{error}</div>
      )}

      <div className="flex flex-wrap gap-2 border-b border-gray-200 dark:border-slate-700 pb-2">
        {sections.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => setSection(s.id)}
            className={`px-3 py-1.5 rounded-md text-sm font-medium ${
              section === s.id
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 dark:bg-slate-800 text-gray-700 dark:text-slate-200 hover:bg-gray-200 dark:hover:bg-slate-700'
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {loading && !overview ? (
        <div className="text-sm text-gray-500 dark:text-slate-400">Loading analytics…</div>
      ) : (
        <>
          {section === 'overview' && overview && inv && (
            <div className="space-y-6">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <MetricCard label="Total Investigations" value={inv.total_investigations} />
                <MetricCard label="Completed" value={inv.completed} sub={`${inv.success_rate_pct}% success`} />
                <MetricCard label="Resolved" value={inv.resolved} />
                <MetricCard label="False Positives" value={inv.false_positives} />
                <MetricCard label="Insufficient Evidence" value={inv.insufficient_evidence} />
                <MetricCard label="Partial Failure" value={inv.partial_failure} />
                <MetricCard label="Failed" value={inv.failed} />
                <MetricCard
                  label="Avg Duration"
                  value={`${(inv.average_duration_ms / 1000).toFixed(1)}s`}
                  sub={`median ${(inv.median_duration_ms / 1000).toFixed(1)}s`}
                />
              </div>

              <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-3">Investigation Quality Score</h3>
                <div className="flex flex-wrap gap-8 items-end">
                  <div>
                    <div className="text-xs text-gray-500 dark:text-slate-400">Overall</div>
                    <QualityScoreBadge score={overview.quality_score.overall_score} />
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 dark:text-slate-400">Last 7 days</div>
                    <QualityScoreBadge score={overview.quality_score.last_7_days} />
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 dark:text-slate-400">Last 30 days</div>
                    <QualityScoreBadge score={overview.quality_score.last_30_days} />
                  </div>
                </div>
              </div>

              <div className="grid md:grid-cols-2 gap-4">
                <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                  <h3 className="text-sm font-semibold mb-2">Investigations (7 days)</h3>
                  <MiniBarChart data={overview.trends.last_7_days || []} valueKey="total" color="bg-blue-500" />
                </div>
                <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                  <h3 className="text-sm font-semibold mb-2">Quality Score (30 days)</h3>
                  <MiniBarChart data={overview.trends.quality_score_daily || []} valueKey="quality_score" color="bg-green-500" />
                </div>
              </div>
            </div>
          )}

          {section === 'templates' && <SortableTemplateTable rows={templates} />}

          {section === 'tools' && <ToolTable rows={tools} />}

          {section === 'proposals' && proposals && <ProposalFunnel proposals={proposals.proposals} />}

          {section === 'root-causes' && rootCauses && (
            <div className="grid md:grid-cols-2 gap-4">
              <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                <h3 className="text-sm font-semibold mb-3">Recurring Issues</h3>
                <ul className="space-y-2 text-sm">
                  {(rootCauses.recurring_incidents || []).map((item) => (
                    <li key={item.key} className="flex justify-between gap-2">
                      <span className="truncate">{item.root_cause}</span>
                      <span className="font-mono text-xs shrink-0">{item.occurrences}x</span>
                    </li>
                  ))}
                  {!rootCauses.recurring_incidents?.length && (
                    <li className="text-gray-500 dark:text-slate-400">No recurring incidents yet</li>
                  )}
                </ul>
              </div>
              <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                <h3 className="text-sm font-semibold mb-3">Active Issues</h3>
                <ul className="space-y-2 text-sm max-h-64 overflow-y-auto">
                  {(rootCauses.active_incidents || []).slice(0, 10).map((item) => (
                    <li key={item.investigation_id} className="border-b border-gray-100 dark:border-slate-700 pb-2">
                      <div className="font-medium truncate">{item.root_cause}</div>
                      <div className="text-xs text-gray-500 dark:text-slate-400 truncate">{item.objective}</div>
                    </li>
                  ))}
                  {!rootCauses.active_incidents?.length && (
                    <li className="text-gray-500 dark:text-slate-400">No active incidents</li>
                  )}
                </ul>
              </div>
              <div className="md:col-span-2 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
                <h3 className="text-sm font-semibold mb-3">Resolved Issues</h3>
                <ul className="space-y-2 text-sm max-h-48 overflow-y-auto">
                  {(rootCauses.resolved_incidents || []).slice(0, 10).map((item) => (
                    <li key={item.investigation_id} className="flex justify-between gap-2">
                      <span className="truncate">{item.root_cause}</span>
                      <span className="text-xs text-gray-500 shrink-0">{item.confidence?.toFixed(0)}%</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
