'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import Badge from '@/components/ui/Badge';
import { generateJarvisActionPlan, getJarvisCryptoAudit, JarvisCryptoAuditRunDetail } from '@/lib/api';

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

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="text-xs bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded p-3 overflow-x-auto whitespace-pre-wrap break-words max-h-[24rem]">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export default function JarvisCryptoAuditDetailPage() {
  const params = useParams();
  const router = useRouter();
  const auditId = typeof params.auditId === 'string' ? params.auditId : '';
  const [detail, setDetail] = useState<JarvisCryptoAuditRunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDetail = useCallback(async () => {
    if (!auditId) return;
    setLoading(true);
    try {
      const data = await getJarvisCryptoAudit(auditId);
      setDetail(data);
      setError(null);
    } catch (err) {
      setDetail(null);
      setError(err instanceof Error ? err.message : 'Failed to load crypto audit detail');
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
      const plan = await generateJarvisActionPlan({ source_type: 'crypto_audit', source_id: auditId });
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
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Crypto Audit Detail</h1>
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
              href="/jarvis/crypto-audits"
              className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              ← All crypto audits
            </Link>
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-300 bg-red-50 dark:bg-red-950/30 text-red-800 dark:text-red-200 px-4 py-3 text-sm">
            {error}
          </div>
        )}

        {loading && !detail ? (
          <p className="text-sm text-gray-500">Loading crypto audit detail…</p>
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
                <dt className="text-gray-500 dark:text-gray-400">Difference USD</dt>
                <dd className="font-mono tabular-nums">${detail.portfolio_difference_usd.toFixed(2)}</dd>
              </div>
              <div>
                <dt className="text-gray-500 dark:text-gray-400">Difference %</dt>
                <dd className="font-mono tabular-nums">{detail.portfolio_difference_pct.toFixed(2)}%</dd>
              </div>
              <div>
                <dt className="text-gray-500 dark:text-gray-400">Findings</dt>
                <dd>{detail.finding_count}</dd>
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
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Wallet findings</h2>
              <JsonBlock value={detail.wallet_findings} />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Position findings</h2>
              <JsonBlock value={detail.position_findings} />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Valuation findings</h2>
              <JsonBlock value={detail.valuation_findings} />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Price feed findings</h2>
              <JsonBlock value={detail.price_feed_findings} />
            </div>
          </div>
        ) : (
          <p className="text-sm text-gray-500">Crypto audit not found.</p>
        )}
      </div>
    </div>
  );
}
