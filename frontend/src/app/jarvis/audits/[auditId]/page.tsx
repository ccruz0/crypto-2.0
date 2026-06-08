'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import Badge from '@/components/ui/Badge';
import { generateJarvisActionPlan, getJarvisAudit, JarvisAuditRunDetail } from '@/lib/api';

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function severityVariant(severity: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (severity === 'high') return 'danger';
  if (severity === 'medium') return 'warning';
  return 'neutral';
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="text-xs bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded p-3 overflow-x-auto whitespace-pre-wrap break-words max-h-[24rem]">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export default function JarvisAuditDetailPage() {
  const params = useParams();
  const router = useRouter();
  const auditId = typeof params.auditId === 'string' ? params.auditId : '';
  const [detail, setDetail] = useState<JarvisAuditRunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDetail = useCallback(async () => {
    if (!auditId) return;
    setLoading(true);
    try {
      const data = await getJarvisAudit(auditId);
      setDetail(data);
      setError(null);
    } catch (err) {
      setDetail(null);
      setError(err instanceof Error ? err.message : 'Failed to load audit detail');
    } finally {
      setLoading(false);
    }
  }, [auditId]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  const handleGeneratePlan = async () => {
    if (!auditId) return;
    setGenerating(true);
    try {
      const plan = await generateJarvisActionPlan({ source_type: 'aws_audit', source_id: auditId });
      router.push(`/jarvis/action-plans/${plan.plan_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate action plan');
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <div className="container mx-auto p-4 md:p-8 max-w-7xl">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Audit Detail</h1>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1 font-mono">{auditId}</p>
          </div>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={handleGeneratePlan}
              disabled={generating || !auditId}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
            >
              {generating ? 'Generating…' : 'Generate action plan'}
            </button>
            <Link
              href="/jarvis/audits"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              ← All audits
            </Link>
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-300 bg-red-50 dark:bg-red-950/30 text-red-800 dark:text-red-200 px-4 py-3 text-sm">
            {error}
          </div>
        )}

        {loading && !detail ? (
          <p className="text-sm text-gray-500">Loading audit detail…</p>
        ) : detail ? (
          <div className="space-y-6 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4 md:p-6 shadow-sm">
            <div className="flex flex-wrap gap-2 items-center">
              <Badge variant={severityVariant(detail.severity)}>{detail.severity} severity</Badge>
              <Badge variant="neutral">read-only</Badge>
            </div>

            <dl className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
              <div>
                <dt className="text-gray-500 dark:text-gray-400">Audit date</dt>
                <dd>{formatTimestamp(detail.created_at)}</dd>
              </div>
              <div>
                <dt className="text-gray-500 dark:text-gray-400">Est. monthly savings</dt>
                <dd className="font-mono tabular-nums">${detail.estimated_monthly_savings.toFixed(2)}</dd>
              </div>
              <div>
                <dt className="text-gray-500 dark:text-gray-400">Finding counts</dt>
                <dd>
                  {detail.finding_counts?.total ?? 0} total (
                  {detail.finding_counts?.cost ?? 0} cost, {detail.finding_counts?.security ?? 0} security,{' '}
                  {detail.finding_counts?.resource ?? 0} resource)
                </dd>
              </div>
              <div>
                <dt className="text-gray-500 dark:text-gray-400">task_id</dt>
                <dd className="font-mono text-xs break-all">{detail.task_id || '—'}</dd>
              </div>
            </dl>

            {detail.recommendations && detail.recommendations.length > 0 && (
              <div>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Recommendations</h2>
                <ul className="list-disc pl-5 text-sm space-y-1">
                  {detail.recommendations.map((rec) => (
                    <li key={rec}>{rec}</li>
                  ))}
                </ul>
              </div>
            )}

            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Summary</h2>
              <JsonBlock value={detail.summary} />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Cost findings</h2>
              <JsonBlock value={detail.cost_findings} />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Security findings</h2>
              <JsonBlock value={detail.security_findings} />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Resource findings</h2>
              <JsonBlock value={detail.resource_findings} />
            </div>
          </div>
        ) : (
          <p className="text-sm text-gray-500">Audit not found.</p>
        )}
      </div>
    </div>
  );
}
