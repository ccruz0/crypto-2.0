'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  getJarvisInvestigation,
  listJarvisInvestigations,
  listJarvisInvestigationPresets,
  runJarvisInvestigation,
  type JarvisInvestigationDetail,
  type JarvisInvestigationPreset,
  type JarvisInvestigationSummary,
} from '@/app/api';

function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const variant =
    normalized === 'completed'
      ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200'
      : normalized === 'insufficient_evidence' || normalized === 'failed'
        ? 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200'
        : 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200';
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${variant}`}>
      {status}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.min(100, Math.max(0, value));
  const color = pct >= 80 ? 'bg-green-500' : pct >= 50 ? 'bg-amber-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-200 dark:bg-slate-700 rounded overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono w-10 text-right">{pct.toFixed(0)}%</span>
    </div>
  );
}

export default function ProductionDiagnosticsTab() {
  const [objective, setObjective] = useState('');
  const [presets, setPresets] = useState<JarvisInvestigationPreset[]>([]);
  const [investigations, setInvestigations] = useState<JarvisInvestigationSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<JarvisInvestigationDetail | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshList = useCallback(async (q = '') => {
    try {
      const res = await listJarvisInvestigations(20, q);
      setInvestigations(res.investigations || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load investigations');
    }
  }, []);

  useEffect(() => {
    listJarvisInvestigationPresets()
      .then((res) => setPresets(res.presets || []))
      .catch(() => {});
    refreshList();
  }, [refreshList]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    getJarvisInvestigation(selectedId)
      .then(setDetail)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load detail'));
  }, [selectedId]);

  const handleRun = async () => {
    const text = objective.trim();
    if (!text) return;
    setRunning(true);
    setError(null);
    try {
      const result = await runJarvisInvestigation(text);
      setDetail(result);
      setSelectedId(result.investigation_id);
      await refreshList();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Investigation failed');
    } finally {
      setRunning(false);
    }
  };

  const handleSearch = async () => {
    await refreshList(searchQuery.trim());
  };

  return (
    <div className="space-y-4" data-testid="production-diagnostics-tab">
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-slate-800 p-4">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
          Production Diagnostics
        </h2>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
          Read-only incident investigations across database, exchange, cache, logs, and repository.
        </p>

        <div className="flex flex-wrap gap-2 mb-3">
          {presets.map((preset) => (
            <button
              key={preset.id}
              type="button"
              onClick={() => setObjective(preset.objective)}
              className="px-3 py-1 text-xs rounded-full border border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-slate-700"
            >
              {preset.label}
            </button>
          ))}
        </div>

        <div className="flex gap-2 mb-2">
          <input
            data-testid="diagnostics-objective-input"
            type="text"
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            placeholder="e.g. Why are open orders empty?"
            className="flex-1 px-3 py-2 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-slate-900 text-sm"
          />
          <button
            data-testid="diagnostics-run-button"
            type="button"
            onClick={handleRun}
            disabled={running || !objective.trim()}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium disabled:opacity-50"
          >
            {running ? 'Investigating…' : 'Run Investigation'}
          </button>
        </div>

        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-slate-800 p-4">
          <div className="flex gap-2 mb-3">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search prior incidents"
              className="flex-1 px-2 py-1 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-slate-900"
            />
            <button type="button" onClick={handleSearch} className="px-2 py-1 text-xs border rounded">
              Search
            </button>
          </div>
          <h3 className="text-sm font-medium mb-2">Investigation History</h3>
          <ul className="space-y-2 max-h-96 overflow-y-auto">
            {investigations.map((inv) => (
              <li key={inv.investigation_id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(inv.investigation_id)}
                  className={`w-full text-left p-2 rounded text-xs border ${
                    selectedId === inv.investigation_id
                      ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                      : 'border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-slate-700'
                  }`}
                >
                  <div className="flex justify-between items-center gap-1">
                    <span className="font-mono truncate">{inv.investigation_id.slice(0, 8)}…</span>
                    <StatusBadge status={inv.status} />
                  </div>
                  <p className="truncate mt-1 text-gray-700 dark:text-gray-300">{inv.objective}</p>
                  <div className="flex justify-between mt-1 text-gray-500">
                    <span>{inv.evidence_count} evidence</span>
                    <span>{inv.confidence?.toFixed(0)}%</span>
                  </div>
                </button>
              </li>
            ))}
            {investigations.length === 0 && (
              <li className="text-xs text-gray-500">No investigations yet.</li>
            )}
          </ul>
        </div>

        <div className="lg:col-span-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-slate-800 p-4 space-y-4">
          {!detail ? (
            <p className="text-sm text-gray-500">Select an investigation or run a new diagnostic.</p>
          ) : (
            <>
              <div data-testid="diagnostics-detail-header">
                <div className="flex flex-wrap items-center gap-2 mb-2">
                  <h3 className="font-semibold text-gray-900 dark:text-white">{detail.objective}</h3>
                  <StatusBadge status={detail.status} />
                  <span className="text-xs text-gray-500 font-mono">{detail.investigation_id}</span>
                </div>
                <ConfidenceBar value={detail.confidence} />
              </div>

              <section>
                <h4 className="text-sm font-medium mb-1">Summary</h4>
                <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-line">{detail.summary}</p>
              </section>

              <section>
                <h4 className="text-sm font-medium mb-1">Root Cause</h4>
                <p className="text-sm text-gray-900 dark:text-white font-medium">
                  {detail.root_cause || 'Not determined'}
                </p>
              </section>

              <section>
                <h4 className="text-sm font-medium mb-1">Evidence ({detail.evidence_count})</h4>
                <ul className="space-y-1 max-h-40 overflow-y-auto text-xs">
                  {(detail.evidence || []).map((ev, idx) => (
                    <li key={idx} className="p-2 rounded bg-gray-50 dark:bg-slate-900/60">
                      <span className="font-mono text-gray-500">
                        [{ev.source}|{ev.reference}|{ev.confidence}]
                      </span>{' '}
                      {ev.detail}
                    </li>
                  ))}
                </ul>
              </section>

              <section>
                <h4 className="text-sm font-medium mb-1">Ranked Causes</h4>
                <ul className="space-y-2">
                  {(detail.ranked_causes || []).map((cause, idx) => (
                    <li
                      key={idx}
                      className="p-2 rounded border border-gray-200 dark:border-gray-700 text-xs"
                    >
                      <div className="flex justify-between">
                        <span className="font-medium">{cause.cause}</span>
                        <span className="font-mono">{cause.score.toFixed(0)}</span>
                      </div>
                      {cause.explanation && (
                        <p className="text-gray-500 mt-1">{cause.explanation}</p>
                      )}
                    </li>
                  ))}
                </ul>
              </section>

              <section>
                <h4 className="text-sm font-medium mb-1">Recommended Fix</h4>
                <p className="text-sm text-gray-700 dark:text-gray-300">{detail.recommended_fix}</p>
              </section>

              <section>
                <h4 className="text-sm font-medium mb-1">Impact</h4>
                <p className="text-sm text-gray-600 dark:text-gray-400">{detail.impact}</p>
              </section>

              <section>
                <h4 className="text-sm font-medium mb-1">Verification Steps</h4>
                <ol className="list-decimal list-inside text-sm text-gray-600 dark:text-gray-400">
                  {(detail.verification_steps || []).map((step, idx) => (
                    <li key={idx}>{step}</li>
                  ))}
                </ol>
              </section>

              <section>
                <h4 className="text-sm font-medium mb-1">Next Action</h4>
                <p className="text-sm text-gray-700 dark:text-gray-300">{detail.next_action}</p>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
