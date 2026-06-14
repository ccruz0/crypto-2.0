'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  getJarvisImprovementRecommendations,
  getJarvisImprovementTemplates,
  getJarvisImprovementTools,
  getJarvisImprovementTrends,
  type JarvisImprovementRecommendation,
  type JarvisImprovementTemplateGap,
  type JarvisImprovementToolEffectiveness,
  type JarvisImprovementTrends,
} from '@/app/api';

type Section = 'recommendations' | 'template-gaps' | 'tool-efficiency' | 'quality-trends' | 'backlog';

function PriorityBadge({ priority }: { priority: string }) {
  const colors: Record<string, string> = {
    high: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
    medium: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
    low: 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300',
  };
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold uppercase ${colors[priority] || colors.low}`}>
      {priority}
    </span>
  );
}

function RecommendationCard({ rec, rank }: { rec: JarvisImprovementRecommendation; rank?: number }) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4 space-y-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          {rank !== undefined && (
            <span className="text-lg font-bold text-gray-400 dark:text-slate-500">#{rank}</span>
          )}
          <h3 className="font-semibold text-gray-900 dark:text-white">{rec.title}</h3>
        </div>
        <div className="flex items-center gap-2">
          <PriorityBadge priority={rec.priority} />
          <span className="text-xs text-gray-500 dark:text-slate-400">Score: {rec.priority_score.toFixed(1)}</span>
        </div>
      </div>
      <p className="text-sm text-gray-700 dark:text-slate-300">{rec.recommendation}</p>
      <div className="text-xs text-gray-500 dark:text-slate-400">
        <span className="font-medium">Reason:</span> {rec.reason}
      </div>
      {rec.evidence.length > 0 && (
        <ul className="text-xs text-gray-600 dark:text-slate-400 list-disc list-inside space-y-0.5">
          {rec.evidence.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-3 text-xs text-gray-500 dark:text-slate-400 pt-1 border-t border-gray-100 dark:border-slate-700">
        <span>Impact: {rec.impact}</span>
        <span>Frequency: {rec.frequency}</span>
        <span>Confidence: {rec.confidence.toFixed(0)}%</span>
        {rec.expected_benefit && <span>Benefit: {rec.expected_benefit}</span>}
      </div>
    </div>
  );
}

function GapTable({ gaps }: { gaps: JarvisImprovementTemplateGap[] }) {
  if (gaps.length === 0) {
    return <p className="text-sm text-gray-500 dark:text-slate-400">No template gaps detected.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm" data-testid="jarvis-improvement-gaps-table">
        <thead className="bg-gray-50 dark:bg-slate-900/50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Gap Type</th>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Template / Category</th>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Investigations</th>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Severity</th>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Detail</th>
          </tr>
        </thead>
        <tbody>
          {gaps.map((gap, i) => (
            <tr key={i} className="border-t border-gray-100 dark:border-slate-700">
              <td className="px-3 py-2 font-mono text-xs">{gap.gap_type}</td>
              <td className="px-3 py-2 font-mono text-xs">{gap.template_id || gap.category || '—'}</td>
              <td className="px-3 py-2">{gap.investigations}</td>
              <td className="px-3 py-2">
                <PriorityBadge priority={gap.severity === 'high' ? 'high' : gap.severity === 'medium' ? 'medium' : 'low'} />
              </td>
              <td className="px-3 py-2 text-xs text-gray-600 dark:text-slate-400">
                {gap.insufficient_evidence_rate_pct !== undefined && `${gap.insufficient_evidence_rate_pct}% insufficient`}
                {gap.generic_rate_pct !== undefined && `${gap.generic_rate_pct}% generic`}
                {gap.failure_rate_pct !== undefined && `${gap.failure_rate_pct}% failure`}
                {gap.top_keywords && gap.top_keywords.length > 0 && `Keywords: ${gap.top_keywords.join(', ')}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ToolEfficiencyTable({ tools }: { tools: JarvisImprovementToolEffectiveness[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm" data-testid="jarvis-improvement-tools-table">
        <thead className="bg-gray-50 dark:bg-slate-900/50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Tool</th>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Executions</th>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Success %</th>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Useful Outcomes</th>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Utility Ratio</th>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Assessment</th>
          </tr>
        </thead>
        <tbody>
          {tools.map((row) => (
            <tr key={row.tool} className="border-t border-gray-100 dark:border-slate-700">
              <td className="px-3 py-2 font-mono text-xs">{row.tool}</td>
              <td className="px-3 py-2">{row.executions}</td>
              <td className="px-3 py-2">{row.success_rate_pct.toFixed(1)}%</td>
              <td className="px-3 py-2">{row.useful_outcomes}</td>
              <td className="px-3 py-2">{(row.utility_ratio * 100).toFixed(1)}%</td>
              <td className="px-3 py-2">
                <span
                  className={`text-xs font-medium ${
                    row.assessment === 'high_value'
                      ? 'text-green-600 dark:text-green-400'
                      : row.assessment === 'low_utility'
                        ? 'text-red-600 dark:text-red-400'
                        : 'text-gray-600 dark:text-slate-400'
                  }`}
                >
                  {row.assessment.replace('_', ' ')}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function QualityTrendsPanel({ trends }: { trends: JarvisImprovementTrends }) {
  const qs = trends.quality_scores;
  const fp = trends.false_positives;
  const direction = String(qs.trend_direction || 'stable');
  const directionColor =
    direction === 'improving'
      ? 'text-green-600 dark:text-green-400'
      : direction === 'declining'
        ? 'text-red-600 dark:text-red-400'
        : 'text-gray-600 dark:text-slate-400';

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
          <div className="text-xs uppercase text-gray-500 dark:text-slate-400">Overall Score</div>
          <div className="text-2xl font-bold text-gray-900 dark:text-white">{Number(qs.overall || 0).toFixed(1)}</div>
        </div>
        <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
          <div className="text-xs uppercase text-gray-500 dark:text-slate-400">7-Day Score</div>
          <div className="text-2xl font-bold text-gray-900 dark:text-white">{Number(qs.last_7_days || 0).toFixed(1)}</div>
          <div className={`text-xs mt-1 ${directionColor}`}>
            {direction} ({Number(qs.delta_7d || 0) > 0 ? '+' : ''}
            {Number(qs.delta_7d || 0).toFixed(1)})
          </div>
        </div>
        <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
          <div className="text-xs uppercase text-gray-500 dark:text-slate-400">False Positives (7d)</div>
          <div className="text-2xl font-bold text-gray-900 dark:text-white">{fp.last_7_days || 0}</div>
          <div className="text-xs text-gray-500 dark:text-slate-400">{Number(fp.rate_7d_pct || 0).toFixed(1)}% rate</div>
        </div>
        <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
          <div className="text-xs uppercase text-gray-500 dark:text-slate-400">Open Orders Share</div>
          <div className="text-2xl font-bold text-gray-900 dark:text-white">{trends.open_orders_share_pct.toFixed(0)}%</div>
        </div>
      </div>

      {trends.recurring_incidents.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">Recurring Incidents</h3>
          <ul className="space-y-1 text-sm text-gray-700 dark:text-slate-300">
            {trends.recurring_incidents.map((inc, i) => (
              <li key={i} className="flex justify-between gap-2 border-b border-gray-100 dark:border-slate-700 py-1">
                <span className="truncate">{inc.root_cause}</span>
                <span className="text-xs text-gray-500 shrink-0">{inc.occurrences}×</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {trends.recommendations.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Trend Recommendations</h3>
          {trends.recommendations.map((rec) => (
            <RecommendationCard key={rec.id} rec={rec} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function JarvisImprovementTab() {
  const [section, setSection] = useState<Section>('recommendations');
  const [recommendations, setRecommendations] = useState<JarvisImprovementRecommendation[]>([]);
  const [backlog, setBacklog] = useState<JarvisImprovementRecommendation[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [templateData, setTemplateData] = useState<Awaited<ReturnType<typeof getJarvisImprovementTemplates>> | null>(null);
  const [toolData, setToolData] = useState<Awaited<ReturnType<typeof getJarvisImprovementTools>> | null>(null);
  const [trendData, setTrendData] = useState<JarvisImprovementTrends | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [recs, tmpl, tools, trends] = await Promise.all([
        getJarvisImprovementRecommendations(),
        getJarvisImprovementTemplates(),
        getJarvisImprovementTools(),
        getJarvisImprovementTrends(),
      ]);
      setRecommendations(recs.recommendations || []);
      setBacklog(recs.backlog || []);
      setCounts(recs.counts || {});
      setTemplateData(tmpl);
      setToolData(tools);
      setTrendData(trends);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load improvement data');
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
    { id: 'recommendations', label: 'Recommendations' },
    { id: 'template-gaps', label: 'Template Gaps' },
    { id: 'tool-efficiency', label: 'Tool Efficiency' },
    { id: 'quality-trends', label: 'Quality Trends' },
    { id: 'backlog', label: 'Improvement Backlog' },
  ];

  const highPriority = recommendations.filter((r) => r.priority === 'high');
  const mediumPriority = recommendations.filter((r) => r.priority === 'medium');

  return (
    <div className="space-y-4" data-testid="jarvis-improvement-tab">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">Jarvis Improvement</h2>
          <p className="text-sm text-gray-500 dark:text-slate-400">
            Self-improvement recommendations from investigation analytics (read-only)
          </p>
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

      {!loading && recommendations.length > 0 && (
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/10 p-3 text-center">
            <div className="text-2xl font-bold text-red-700 dark:text-red-300">{counts.high || highPriority.length}</div>
            <div className="text-xs uppercase text-red-600 dark:text-red-400">High Priority</div>
          </div>
          <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/10 p-3 text-center">
            <div className="text-2xl font-bold text-amber-700 dark:text-amber-300">{counts.medium || mediumPriority.length}</div>
            <div className="text-xs uppercase text-amber-600 dark:text-amber-400">Medium Priority</div>
          </div>
          <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800 p-3 text-center">
            <div className="text-2xl font-bold text-gray-700 dark:text-slate-300">{counts.total || recommendations.length}</div>
            <div className="text-xs uppercase text-gray-500 dark:text-slate-400">Total Recommendations</div>
          </div>
        </div>
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

      {loading && recommendations.length === 0 ? (
        <div className="text-sm text-gray-500 dark:text-slate-400">Loading improvement recommendations…</div>
      ) : (
        <>
          {section === 'recommendations' && (
            <div className="space-y-4">
              {highPriority.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-red-700 dark:text-red-300 mb-2 uppercase">High Priority</h3>
                  <div className="space-y-3">
                    {highPriority.map((rec) => (
                      <RecommendationCard key={rec.id} rec={rec} />
                    ))}
                  </div>
                </div>
              )}
              {mediumPriority.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-amber-700 dark:text-amber-300 mb-2 uppercase">Medium Priority</h3>
                  <div className="space-y-3">
                    {mediumPriority.map((rec) => (
                      <RecommendationCard key={rec.id} rec={rec} />
                    ))}
                  </div>
                </div>
              )}
              {recommendations.filter((r) => r.priority === 'low').map((rec) => (
                <RecommendationCard key={rec.id} rec={rec} />
              ))}
              {recommendations.length === 0 && (
                <p className="text-sm text-gray-500 dark:text-slate-400">No recommendations yet — run more investigations to generate insights.</p>
              )}
            </div>
          )}

          {section === 'template-gaps' && templateData && (
            <div className="space-y-4">
              <GapTable gaps={templateData.gaps} />
              {templateData.recommendations.length > 0 && (
                <div className="space-y-3 mt-4">
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Template Gap Recommendations</h3>
                  {templateData.recommendations.map((rec) => (
                    <RecommendationCard key={rec.id} rec={rec} />
                  ))}
                </div>
              )}
            </div>
          )}

          {section === 'tool-efficiency' && toolData && (
            <div className="space-y-4">
              <ToolEfficiencyTable tools={toolData.tools} />
              {toolData.recommendations.length > 0 && (
                <div className="space-y-3 mt-4">
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Tool Optimization Recommendations</h3>
                  {toolData.recommendations.map((rec) => (
                    <RecommendationCard key={rec.id} rec={rec} />
                  ))}
                </div>
              )}
            </div>
          )}

          {section === 'quality-trends' && trendData && <QualityTrendsPanel trends={trendData} />}

          {section === 'backlog' && (
            <div className="space-y-3" data-testid="jarvis-improvement-backlog">
              {backlog.map((rec, idx) => (
                <RecommendationCard key={rec.id} rec={rec} rank={idx + 1} />
              ))}
              {backlog.length === 0 && (
                <p className="text-sm text-gray-500 dark:text-slate-400">Backlog empty — insufficient investigation data.</p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
