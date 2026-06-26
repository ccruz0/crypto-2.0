'use client';

import React, { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { flushSync } from 'react-dom';
import Link from 'next/link';
import {
  deriveNotionPageUrl,
  fetchGovernanceTimeline,
  filterTimelineForView,
  findLatestTimelineIndexBySignal,
  formatActor,
  formatCompactPayloadPretty,
  formatLinksSummary,
  governanceTimelineAbsoluteUrl,
  indexOfLatestManifestByCreatedAt,
  normalizeSignalCounts,
  parseTimelineEventSignal,
  readStoredGovernanceBearer,
  resolveGovernanceLookup,
  storeGovernanceBearer,
  type GovernanceResolveResponse,
  type GovernanceTimelineEvent,
  type GovernanceTimelineResponse,
  type TimelineSignal,
  type TimelineSignalFilter,
} from '@/lib/governanceTaskView';

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function CopyTextBtn({
  text,
  copyId,
  copiedId,
  setCopiedId,
}: {
  text: string;
  copyId: string;
  copiedId: string | null;
  setCopiedId: React.Dispatch<React.SetStateAction<string | null>>;
}) {
  const done = copiedId === copyId;
  return (
    <button
      type="button"
      onClick={() => {
        void copyToClipboard(text).then((ok) => {
          if (ok) {
            setCopiedId(copyId);
            window.setTimeout(() => {
              setCopiedId((c) => (c === copyId ? null : c));
            }, 1800);
          }
        });
      }}
      className="ml-1.5 inline-flex shrink-0 items-center rounded border border-slate-600 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-400 hover:border-slate-500 hover:bg-slate-800 hover:text-slate-200"
      title="Copy to clipboard"
    >
      {done ? 'Copied' : 'Copy'}
    </button>
  );
}

function FieldRow({
  label,
  value,
  copyId,
  copiedId,
  setCopiedId,
  mono = true,
  showCopy = true,
  children,
}: {
  label: string;
  value: string | null | undefined;
  copyId: string;
  copiedId: string | null;
  setCopiedId: React.Dispatch<React.SetStateAction<string | null>>;
  mono?: boolean;
  showCopy?: boolean;
  children?: React.ReactNode;
}) {
  const v = value?.trim() || '';
  const display = v || '—';
  return (
    <div className="min-w-0">
      <div className="text-slate-500 text-xs mb-0.5">{label}</div>
      <div className={`flex flex-wrap items-start gap-x-0 text-sm break-all min-w-0 ${mono ? 'font-mono' : ''}`}>
        <span className={v ? (mono ? 'text-sky-300' : 'text-slate-100') : 'text-slate-500'}>{display}</span>
        {v && showCopy ? (
          <CopyTextBtn text={v} copyId={copyId} copiedId={copiedId} setCopiedId={setCopiedId} />
        ) : null}
        {children}
      </div>
    </div>
  );
}

function scopeStyles(scope: string): { border: string; bg: string; title: string } {
  switch (scope) {
    case 'full':
      return {
        border: 'border-emerald-600/50',
        bg: 'bg-emerald-950/30',
        title: 'Coverage: full (Notion-linked + agent approval row)',
      };
    case 'partial':
      return {
        border: 'border-amber-600/50',
        bg: 'bg-amber-950/25',
        title: 'Coverage: partial (legacy or missing agent bundle / events)',
      };
    default:
      return {
        border: 'border-slate-600/50',
        bg: 'bg-slate-800/40',
        title: 'Coverage: governed_only or reduced linkage',
      };
  }
}

function signalBadgeClasses(signal: TimelineSignal): string {
  switch (signal) {
    case 'failed':
      return 'bg-red-950/80 text-red-200 border-red-700/60';
    case 'drift':
      return 'bg-amber-950/80 text-amber-200 border-amber-700/60';
    case 'classification_conflict':
      return 'bg-violet-950/80 text-violet-200 border-violet-700/60';
    case 'blocked':
      return 'bg-orange-950/80 text-orange-200 border-orange-700/60';
    default:
      return 'bg-slate-800 text-slate-300 border-slate-600';
  }
}

function timelineRowClasses(signal: TimelineSignal | null): string {
  if (!signal) return '';
  switch (signal) {
    case 'failed':
      return 'bg-red-950/25 border-l-2 border-l-red-500';
    case 'drift':
      return 'bg-amber-950/20 border-l-2 border-l-amber-500';
    case 'classification_conflict':
      return 'bg-violet-950/20 border-l-2 border-l-violet-500';
    case 'blocked':
      return 'bg-orange-950/20 border-l-2 border-l-orange-500';
    default:
      return '';
  }
}

function flashOutlineClass(active: boolean): string {
  return active ? ' ring-2 ring-sky-400/90 ring-offset-2 ring-offset-slate-950 rounded-sm transition-[box-shadow] duration-150' : '';
}

function signalLabel(s: TimelineSignal): string {
  switch (s) {
    case 'failed':
      return 'FAILED';
    case 'drift':
      return 'DRIFT';
    case 'classification_conflict':
      return 'CLASS CONFLICT';
    case 'blocked':
      return 'BLOCKED';
    default:
      return s;
  }
}

function TimelineExpandedDetails({
  ev,
  rowKey,
  copiedId,
  setCopiedId,
}: {
  ev: GovernanceTimelineEvent;
  rowKey: string;
  copiedId: string | null;
  setCopiedId: React.Dispatch<React.SetStateAction<string | null>>;
}) {
  const json = formatCompactPayloadPretty(ev.compact_payload);
  const payloadRef = (ev.payload_ref || '').trim();
  const linkEntries = ev.links && typeof ev.links === 'object' ? Object.entries(ev.links) : [];

  return (
    <div
      className="space-y-2 py-1 pl-1 text-xs text-slate-300"
      id={`gov-timeline-details-${rowKey}`}
      role="region"
      aria-label="Timeline event details"
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1">
        {(ev.environment || '').trim() ? (
          <div>
            <div className="text-slate-500 text-[10px] uppercase tracking-wide">environment</div>
            <div className="font-mono text-slate-200">{ev.environment}</div>
          </div>
        ) : null}
        <div>
          <div className="text-slate-500 text-[10px] uppercase tracking-wide">actor</div>
          <div className="text-slate-200">{formatActor(ev)}</div>
        </div>
      </div>
      {payloadRef ? (
        <div>
          <div className="text-slate-500 text-[10px] uppercase tracking-wide mb-0.5">payload_ref</div>
          <div className="flex flex-wrap items-center gap-1 font-mono text-[10px] text-slate-400 break-all">
            {payloadRef}
            <CopyTextBtn text={payloadRef} copyId={`tl-${rowKey}-pref`} copiedId={copiedId} setCopiedId={setCopiedId} />
          </div>
        </div>
      ) : null}
      {linkEntries.length > 0 ? (
        <div>
          <div className="text-slate-500 text-[10px] uppercase tracking-wide mb-0.5">links</div>
          <dl className="grid grid-cols-1 gap-0.5 font-mono text-[10px] text-slate-400">
            {linkEntries.map(([k, v]) => (
              <div key={k} className="flex flex-wrap gap-x-2 gap-y-0">
                <dt className="shrink-0 text-slate-600">{k}</dt>
                <dd className="break-all min-w-0">{v == null || v === '' ? '—' : String(v)}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
      {json ? (
        <div>
          <div className="flex flex-wrap items-center gap-2 mb-0.5">
            <span className="text-slate-500 text-[10px] uppercase tracking-wide">compact_payload</span>
            <CopyTextBtn text={json} copyId={`tl-${rowKey}-json`} copiedId={copiedId} setCopiedId={setCopiedId} />
          </div>
          <pre className="max-h-64 overflow-auto rounded border border-slate-800 bg-slate-950/80 p-2 text-[10px] leading-relaxed text-slate-300 whitespace-pre-wrap break-words">
            {json}
          </pre>
        </div>
      ) : (
        <p className="text-slate-600 text-[10px]">No compact_payload in this row (or empty object).</p>
      )}
    </div>
  );
}

function filterEmptyMessage(signalFilter: TimelineSignalFilter, importantOnly: boolean): string {
  if (importantOnly && signalFilter === 'all') {
    return 'No events with a signal tag in this task (all rows are unlabeled for the read model).';
  }
  if (signalFilter !== 'all') {
    return `No ${signalLabel(signalFilter as TimelineSignal)} events in this task.`;
  }
  return 'No events match the current filters.';
}

const SIGNAL_FILTER_OPTIONS: { value: TimelineSignalFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'failed', label: 'Failed' },
  { value: 'drift', label: 'Drift' },
  { value: 'classification_conflict', label: 'Class conflict' },
  { value: 'blocked', label: 'Blocked' },
];

function ErrorPanel({ message }: { message: string }) {
  const is401 = /\b401\b/.test(message) || message.toLowerCase().includes('unauthorized');
  const is404 = /\b404\b/.test(message) || message.toLowerCase().includes('not found');
  return (
    <div
      className="rounded-lg border border-red-900/60 bg-red-950/40 text-red-100 text-sm px-4 py-3 mb-6 space-y-2"
      role="alert"
    >
      <div className="font-medium text-red-200">Something went wrong</div>
      <p className="text-red-100/90 font-mono text-xs break-words">{message}</p>
      {is401 && (
        <p className="text-xs text-red-200/80 border-t border-red-900/40 pt-2">
          Check that your Bearer token matches <code className="text-red-200">GOVERNANCE_API_TOKEN</code> or{' '}
          <code className="text-red-200">OPENCLAW_API_TOKEN</code> on the API.
        </p>
      )}
      {is404 && (
        <p className="text-xs text-red-200/80 border-t border-red-900/40 pt-2">
          Confirm the id: try a full <code className="text-red-200">gov-notion-…</code> task id, the raw Notion page UUID,
          or an <code className="text-red-200">mfst-…</code> manifest id. Resolve tries task → Notion → manifest.
        </p>
      )}
    </div>
  );
}

export default function GovernanceTaskViewPage() {
  const [query, setQuery] = useState('');
  const [bearerInput, setBearerInput] = useState('');
  const [resolveSnap, setResolveSnap] = useState<GovernanceResolveResponse | null>(null);
  const [resolveTried, setResolveTried] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<GovernanceTimelineResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [signalFilter, setSignalFilter] = useState<TimelineSignalFilter>('all');
  const [importantOnly, setImportantOnly] = useState(false);
  const [flashAnchorId, setFlashAnchorId] = useState<string | null>(null);
  const [expandedTimelineRows, setExpandedTimelineRows] = useState<Set<number>>(() => new Set());

  const runLookup = useCallback(async () => {
    setError(null);
    setResolveSnap(null);
    setResolveTried(null);
    setTimeline(null);
    const token = bearerInput.trim() || readStoredGovernanceBearer();
    if (!token.trim()) {
      setError('Set a Bearer token (same as GOVERNANCE_API_TOKEN / OPENCLAW_API_TOKEN for the API).');
      return;
    }
    storeGovernanceBearer(token);
    setLoading(true);
    try {
      const resolved = await resolveGovernanceLookup(query, token);
      if (!resolved.ok) {
        setError(`${resolved.status}: ${resolved.detail}`);
        return;
      }
      setResolveSnap(resolved.data);
      setResolveTried(resolved.tried);

      const tl = await fetchGovernanceTimeline(resolved.data.governance_task_id, token);
      if (!tl.ok) {
        setError(`Resolved task, but timeline failed (${tl.status}): ${tl.detail}`);
        return;
      }
      setTimeline(tl.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [query, bearerInput]);

  const govTaskKey = timeline?.governance_task_id ?? '';
  useEffect(() => {
    if (!govTaskKey) return;
    setSignalFilter('all');
    setImportantOnly(false);
    setFlashAnchorId(null);
    setExpandedTimelineRows(new Set());
  }, [govTaskKey]);

  const toggleTimelineRowExpand = useCallback((originalIndex: number) => {
    setExpandedTimelineRows((prev) => {
      const next = new Set(prev);
      if (next.has(originalIndex)) next.delete(originalIndex);
      else next.add(originalIndex);
      return next;
    });
  }, []);

  const scrollToGovTarget = useCallback((elementId: string) => {
    const el = typeof document !== 'undefined' ? document.getElementById(elementId) : null;
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setFlashAnchorId(elementId);
    window.setTimeout(() => {
      setFlashAnchorId((cur) => (cur === elementId ? null : cur));
    }, 2200);
  }, []);

  /** Align timeline filters so the target row is visible, then scroll (used by Jump to latest signal buttons). */
  const jumpToLatestTimelineSignal = useCallback(
    (signal: TimelineSignal, rowIndex: number) => {
      flushSync(() => {
        setSignalFilter(signal);
        setImportantOnly(true);
      });
      scrollToGovTarget(`gov-timeline-row-${rowIndex}`);
    },
    [scrollToGovTarget]
  );

  const cov = timeline?.coverage;
  const scope = cov?.timeline_scope ?? '';
  const chip = scopeStyles(scope);
  const signalCounts = timeline ? normalizeSignalCounts(timeline) : null;

  const filteredTimeline = useMemo(() => {
    if (!timeline?.timeline?.length) return [];
    return filterTimelineForView(timeline.timeline, { signalFilter, importantOnly });
  }, [timeline, signalFilter, importantOnly]);

  const latestManifestIdx = useMemo(
    () => (timeline?.manifests?.length ? indexOfLatestManifestByCreatedAt(timeline.manifests) : null),
    [timeline]
  );

  const latestIdxBySignal = useMemo(() => {
    if (!timeline?.timeline?.length) {
      return {
        failed: null as number | null,
        drift: null as number | null,
        classification_conflict: null as number | null,
        blocked: null as number | null,
      };
    }
    const evs = timeline.timeline;
    return {
      failed: findLatestTimelineIndexBySignal(evs, 'failed'),
      drift: findLatestTimelineIndexBySignal(evs, 'drift'),
      classification_conflict: findLatestTimelineIndexBySignal(evs, 'classification_conflict'),
      blocked: findLatestTimelineIndexBySignal(evs, 'blocked'),
    };
  }, [timeline]);
  const openPageUrl =
    timeline && (deriveNotionPageUrl(timeline.source_ref, timeline.notion_page_id) || null);
  const openPageLabel =
    timeline &&
    (() => {
      const ref = (timeline.source_ref || '').trim();
      if (/^https?:\/\//i.test(ref)) return 'Task link (source_ref)';
      if (timeline.notion_page_id) return 'Notion page (inferred URL)';
      return 'Open';
    })();
  const timelineJsonUrl =
    timeline &&
    (resolveSnap?.timeline_by_task_url?.trim() ||
      governanceTimelineAbsoluteUrl(timeline.governance_task_id));

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-4 md:p-8 max-w-6xl mx-auto">
      <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Governance task (read-only)</h1>
          <p className="text-sm text-slate-400 mt-1">
            Unified timeline via resolve + timeline APIs. No writes, no approvals.
          </p>
        </div>
        <Link href="/monitoring" className="text-sm text-sky-400 hover:underline shrink-0">
          ← Monitoring
        </Link>
      </div>

      <section className="rounded-lg border border-slate-700 bg-slate-900/50 p-4 mb-6 space-y-3">
        <label className="block text-sm font-medium text-slate-300">Lookup</label>
        <p className="text-xs text-slate-500">
          Enter a governance <code className="text-slate-400">task_id</code>, Notion{' '}
          <code className="text-slate-400">page_id</code>, or <code className="text-slate-400">manifest_id</code>.
          The page tries resolve as task → Notion → manifest until one matches.
        </p>
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && query.trim() && !loading) void runLookup();
            }}
            placeholder="gov-notion-… · UUID · mfst-…"
            className="flex-1 rounded border border-slate-600 bg-slate-950 px-3 py-2 text-sm font-mono text-slate-100 placeholder:text-slate-600"
            disabled={loading}
          />
          <button
            type="button"
            onClick={() => void runLookup()}
            disabled={loading || !query.trim()}
            className="rounded bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-40"
          >
            {loading ? 'Loading…' : 'Load timeline'}
          </button>
        </div>
        <div className="pt-2 border-t border-slate-700/80">
          <label className="block text-xs font-medium text-slate-400 mb-1">Bearer token (session only)</label>
          <input
            type="password"
            autoComplete="off"
            value={bearerInput}
            onChange={(e) => setBearerInput(e.target.value)}
            placeholder={readStoredGovernanceBearer() ? '•••• (stored in session)' : 'Paste token…'}
            className="w-full rounded border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600"
            disabled={loading}
          />
          <p className="text-xs text-slate-500 mt-1">
            Stored in <code className="text-slate-500">sessionStorage</code> for this tab. Use the same value as{' '}
            <code className="text-slate-500">Authorization: Bearer …</code> for governance curl.
          </p>
        </div>
      </section>

      {error && <ErrorPanel message={error} />}

      {timeline && cov && (
        <div
          className={`rounded-lg border px-3 py-2 mb-6 text-sm ${chip.border} ${chip.bg}`}
          title={chip.title}
        >
          <div className="font-medium text-slate-200">{chip.title}</div>
          <ul className="mt-2 grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 text-xs text-slate-400">
            <li>
              notion_linked: <span className="text-slate-200">{String(cov.notion_linked)}</span>
            </li>
            <li>
              agent_bundle_present: <span className="text-slate-200">{String(cov.agent_bundle_present)}</span>
            </li>
            <li>
              has_manifests: <span className="text-slate-200">{String(cov.has_manifests)}</span>
            </li>
            <li>
              has_events: <span className="text-slate-200">{String(cov.has_events)}</span>
            </li>
            <li>
              timeline_scope: <span className="text-slate-200">{cov.timeline_scope}</span>
            </li>
          </ul>
          {resolveTried && (
            <p className="text-xs text-slate-500 mt-2">Resolved via query: {resolveTried}</p>
          )}
        </div>
      )}

      {timeline && (
        <>
          <nav
            className="rounded-lg border border-slate-700 bg-slate-900/30 px-3 py-2.5 mb-4 text-xs"
            aria-label="Quick navigation"
          >
            <div className="text-slate-500 mb-2 font-medium uppercase tracking-wide text-[10px]">Quick navigation</div>
            <div className="flex flex-wrap gap-x-2 gap-y-1 items-center text-slate-400">
              <span className="text-slate-600">Sections:</span>
              <a href="#gov-section-task" className="text-sky-400 hover:underline">
                Task
              </a>
              <span className="text-slate-700">·</span>
              <a href="#gov-section-manifests" className="text-sky-400 hover:underline">
                Manifests
              </a>
              <span className="text-slate-700">·</span>
              <a href="#gov-section-agent-bundle" className="text-sky-400 hover:underline">
                Agent bundle
              </a>
              <span className="text-slate-700">·</span>
              <a href="#gov-section-timeline" className="text-sky-400 hover:underline">
                Timeline
              </a>
            </div>
            <div className="mt-2.5 flex flex-wrap gap-1.5 items-center border-t border-slate-800/80 pt-2">
              <span className="text-slate-600 mr-1 shrink-0">Jump to latest:</span>
              <button
                type="button"
                disabled={latestManifestIdx === null}
                title={latestManifestIdx === null ? 'No manifests for this task' : 'Scroll to newest manifest row (by created_at)'}
                onClick={() => {
                  if (latestManifestIdx === null) return;
                  scrollToGovTarget(`gov-manifest-row-${latestManifestIdx}`);
                }}
                className="rounded border border-slate-600 bg-slate-900 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-slate-800 hover:border-slate-500 disabled:opacity-35 disabled:cursor-not-allowed"
              >
                Manifest
              </button>
              <button
                type="button"
                disabled={latestIdxBySignal.failed === null}
                title={
                  latestIdxBySignal.failed === null
                    ? 'No failed-tagged events'
                    : 'Sets filter to Failed + Important only, then scrolls to the latest failed row'
                }
                onClick={() => {
                  const i = latestIdxBySignal.failed;
                  if (i === null) return;
                  jumpToLatestTimelineSignal('failed', i);
                }}
                className="rounded border border-slate-600 bg-slate-900 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-slate-800 hover:border-slate-500 disabled:opacity-35 disabled:cursor-not-allowed"
              >
                Failed
              </button>
              <button
                type="button"
                disabled={latestIdxBySignal.blocked === null}
                title={
                  latestIdxBySignal.blocked === null
                    ? 'No blocked-tagged events'
                    : 'Sets filter to Blocked + Important only, then scrolls to the latest blocked row'
                }
                onClick={() => {
                  const i = latestIdxBySignal.blocked;
                  if (i === null) return;
                  jumpToLatestTimelineSignal('blocked', i);
                }}
                className="rounded border border-slate-600 bg-slate-900 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-slate-800 hover:border-slate-500 disabled:opacity-35 disabled:cursor-not-allowed"
              >
                Blocked
              </button>
              <button
                type="button"
                disabled={latestIdxBySignal.drift === null}
                title={
                  latestIdxBySignal.drift === null
                    ? 'No drift-tagged events'
                    : 'Sets filter to Drift + Important only, then scrolls to the latest drift row'
                }
                onClick={() => {
                  const i = latestIdxBySignal.drift;
                  if (i === null) return;
                  jumpToLatestTimelineSignal('drift', i);
                }}
                className="rounded border border-slate-600 bg-slate-900 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-slate-800 hover:border-slate-500 disabled:opacity-35 disabled:cursor-not-allowed"
              >
                Drift
              </button>
              <button
                type="button"
                disabled={latestIdxBySignal.classification_conflict === null}
                title={
                  latestIdxBySignal.classification_conflict === null
                    ? 'No classification_conflict events'
                    : 'Sets filter to Class conflict + Important only, then scrolls to the latest row'
                }
                onClick={() => {
                  const i = latestIdxBySignal.classification_conflict;
                  if (i === null) return;
                  jumpToLatestTimelineSignal('classification_conflict', i);
                }}
                className="rounded border border-slate-600 bg-slate-900 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-slate-800 hover:border-slate-500 disabled:opacity-35 disabled:cursor-not-allowed"
              >
                Class conflict
              </button>
            </div>
          </nav>

          <section id="gov-section-task" className="rounded-lg border border-slate-700 bg-slate-900/40 p-4 mb-6 scroll-mt-4">
            <h2 className="text-sm font-semibold text-slate-200 mb-3">Task</h2>
            {(openPageUrl || timelineJsonUrl) && (
              <div className="mb-4 flex flex-col gap-2 text-xs border-b border-slate-800/80 pb-4">
                {openPageUrl && (
                  <div>
                    <span className="text-slate-500">{openPageLabel}: </span>
                    <a
                      href={openPageUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sky-400 hover:underline break-all"
                    >
                      {openPageUrl}
                    </a>
                    <CopyTextBtn
                      text={openPageUrl}
                      copyId="link-open-page"
                      copiedId={copiedId}
                      setCopiedId={setCopiedId}
                    />
                  </div>
                )}
                {timelineJsonUrl && (
                  <div>
                    <span className="text-slate-500">Timeline API (GET, needs Bearer in curl or extension): </span>
                    <a
                      href={timelineJsonUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sky-400 hover:underline break-all"
                    >
                      {timelineJsonUrl}
                    </a>
                    <CopyTextBtn
                      text={timelineJsonUrl}
                      copyId="link-timeline"
                      copiedId={copiedId}
                      setCopiedId={setCopiedId}
                    />
                  </div>
                )}
              </div>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
              <FieldRow
                label="governance_task_id"
                value={timeline.governance_task_id}
                copyId="task-gov-id"
                copiedId={copiedId}
                setCopiedId={setCopiedId}
              />
              <FieldRow
                label="notion_page_id"
                value={timeline.notion_page_id ?? undefined}
                copyId="task-notion-id"
                copiedId={copiedId}
                setCopiedId={setCopiedId}
              />
              <div className="min-w-0">
                <div className="text-slate-500 text-xs mb-0.5">current_status</div>
                <div className="text-slate-100 flex flex-wrap items-center gap-2 min-w-0 text-sm">
                  <span>{timeline.current_status}</span>
                  {['failed', 'blocked'].includes((timeline.current_status || '').toLowerCase()) && (
                    <span className="rounded border border-red-700/50 bg-red-950/50 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-red-200">
                      Attention
                    </span>
                  )}
                </div>
              </div>
              <FieldRow
                label="risk_level"
                value={timeline.risk_level ?? undefined}
                copyId="task-risk"
                copiedId={copiedId}
                setCopiedId={setCopiedId}
                mono={false}
                showCopy={false}
              />
              <div className="sm:col-span-2 min-w-0">
                <div className="text-slate-500 text-xs mb-0.5">source_type / ref</div>
                <div className="text-slate-300 break-all text-xs">
                  {timeline.source_type ?? '—'} {timeline.source_ref ? `· ${timeline.source_ref}` : ''}
                </div>
              </div>
              <FieldRow
                label="current_manifest_id"
                value={timeline.current_manifest_id ?? undefined}
                copyId="task-current-mfst"
                copiedId={copiedId}
                setCopiedId={setCopiedId}
              />
              <FieldRow
                label="task_created_at"
                value={timeline.task_created_at ?? undefined}
                copyId="task-created"
                copiedId={copiedId}
                setCopiedId={setCopiedId}
                mono={false}
              />
              <FieldRow
                label="task_updated_at"
                value={timeline.task_updated_at ?? undefined}
                copyId="task-updated"
                copiedId={copiedId}
                setCopiedId={setCopiedId}
                mono={false}
              />
            </div>
            {resolveSnap && (
              <div className="mt-3 pt-3 border-t border-slate-800/80">
                <p className="text-xs text-slate-500 mb-1">latest_manifest_id (from resolve)</p>
                <div className="flex flex-wrap items-center font-mono text-xs text-slate-400 break-all">
                  {resolveSnap.latest_manifest_id ?? '—'}
                  {resolveSnap.latest_manifest_id ? (
                    <CopyTextBtn
                      text={resolveSnap.latest_manifest_id}
                      copyId="resolve-latest-mfst"
                      copiedId={copiedId}
                      setCopiedId={setCopiedId}
                    />
                  ) : null}
                </div>
              </div>
            )}
          </section>

          <section
            id="gov-section-manifests"
            className="rounded-lg border border-slate-700 bg-slate-900/40 p-4 mb-6 overflow-x-auto scroll-mt-4"
          >
            <h2 className="text-sm font-semibold text-slate-200 mb-3">Manifests</h2>
            {timeline.manifests.length === 0 ? (
              <div className="text-sm text-slate-500 space-y-1">
                <p>No manifests for this task.</p>
                <p className="text-xs text-slate-600">
                  If you expected execution under enforce, the task may not have crossed manifest creation yet, or this
                  is a manual / non–prod-mutation path.
                </p>
              </div>
            ) : (
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-slate-700 text-slate-500">
                    <th className="py-2 pr-3 font-medium">manifest_id</th>
                    <th className="py-2 pr-3 font-medium">approval</th>
                    <th className="py-2 pr-3 font-medium">digest_prefix</th>
                    <th className="py-2 pr-3 font-medium">bundle_fp prefix</th>
                    <th className="py-2 pr-3 font-medium">created_at</th>
                    <th className="py-2 pr-3 font-medium">expires_at</th>
                  </tr>
                </thead>
                <tbody>
                  {timeline.manifests.map((m, mi) => (
                    <tr
                      key={m.manifest_id}
                      id={`gov-manifest-row-${mi}`}
                      className={`border-b border-slate-800/80${flashOutlineClass(flashAnchorId === `gov-manifest-row-${mi}`)}`}
                    >
                      <td className="py-2 pr-3 font-mono text-sky-300 break-all align-top">
                        <span className="whitespace-pre-wrap">{m.manifest_id}</span>
                        <CopyTextBtn
                          text={m.manifest_id}
                          copyId={`mfst-${m.manifest_id}`}
                          copiedId={copiedId}
                          setCopiedId={setCopiedId}
                        />
                      </td>
                      <td className="py-2 pr-3 text-slate-200 align-top">{m.approval_status}</td>
                      <td className="py-2 pr-3 font-mono text-slate-400 align-top">
                        {m.digest_prefix ?? '—'}
                        {m.digest_prefix ? (
                          <CopyTextBtn
                            text={m.digest_prefix}
                            copyId={`digest-${m.manifest_id}`}
                            copiedId={copiedId}
                            setCopiedId={setCopiedId}
                          />
                        ) : null}
                      </td>
                      <td className="py-2 pr-3 font-mono text-slate-500 align-top text-[10px]">
                        {m.bundle_fingerprint_prefix ?? '—'}
                        {m.bundle_fingerprint_prefix ? (
                          <CopyTextBtn
                            text={m.bundle_fingerprint_prefix}
                            copyId={`mbfp-${m.manifest_id}`}
                            copiedId={copiedId}
                            setCopiedId={setCopiedId}
                          />
                        ) : null}
                      </td>
                      <td className="py-2 pr-3 text-slate-400 whitespace-nowrap align-top">{m.created_at ?? '—'}</td>
                      <td className="py-2 pr-3 text-slate-400 whitespace-nowrap align-top">{m.expires_at ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section id="gov-section-agent-bundle" className="rounded-lg border border-slate-700 bg-slate-900/40 p-4 mb-6 scroll-mt-4">
            <h2 className="text-sm font-semibold text-slate-200 mb-3">Agent bundle</h2>
            {!timeline.agent_bundle ? (
              <div className="text-sm text-slate-500 space-y-1">
                <p>
                  No <code className="text-slate-600">agent_approval_states</code> row for this Notion id (common for
                  manual tasks or deploy-only paths).
                </p>
                <p className="text-xs text-slate-600">
                  Coverage <code className="text-slate-600">timeline_scope: partial</code> often means the governance task
                  exists without a linked Telegram approval row.
                </p>
              </div>
            ) : (
              <dl className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
                <div>
                  <dt className="text-slate-500 text-xs">bundle_fingerprint_prefix</dt>
                  <dd className="flex flex-wrap items-start font-mono text-xs break-all text-slate-300">
                    {timeline.agent_bundle.bundle_fingerprint_prefix ?? '—'}
                    {timeline.agent_bundle.bundle_fingerprint_prefix ? (
                      <CopyTextBtn
                        text={timeline.agent_bundle.bundle_fingerprint_prefix}
                        copyId="bundle-fp-prefix"
                        copiedId={copiedId}
                        setCopiedId={setCopiedId}
                      />
                    ) : null}
                  </dd>
                </div>
                <div>
                  <dt className="text-slate-500 text-xs">governance_action_class</dt>
                  <dd className="text-slate-200">{timeline.agent_bundle.governance_action_class ?? '—'}</dd>
                </div>
                <div>
                  <dt className="text-slate-500 text-xs">approval_row_status</dt>
                  <dd className="text-slate-200">{timeline.agent_bundle.approval_row_status ?? '—'}</dd>
                </div>
                <div>
                  <dt className="text-slate-500 text-xs">execution_status</dt>
                  <dd className="text-slate-200">{timeline.agent_bundle.execution_status ?? '—'}</dd>
                </div>
                {timeline.agent_bundle.selection_reason && (
                  <div className="sm:col-span-2">
                    <dt className="text-slate-500 text-xs">selection_reason</dt>
                    <dd className="text-slate-400 text-xs">{timeline.agent_bundle.selection_reason}</dd>
                  </div>
                )}
              </dl>
            )}
          </section>

          <section
            id="gov-section-timeline"
            className="rounded-lg border border-slate-700 bg-slate-900/40 p-4 mb-8 overflow-x-auto scroll-mt-4"
          >
            <h2 className="text-sm font-semibold text-slate-200 mb-3">Timeline</h2>
            <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-3">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[10px] font-medium uppercase tracking-wide text-slate-500">Signal</span>
                {SIGNAL_FILTER_OPTIONS.map(({ value, label }) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setSignalFilter(value)}
                    className={`rounded border px-2 py-0.5 text-[11px] font-medium ${
                      signalFilter === value
                        ? 'border-sky-500 bg-sky-950/50 text-sky-200'
                        : 'border-slate-600 bg-slate-900 text-slate-400 hover:border-slate-500 hover:text-slate-200'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <label className="inline-flex items-center gap-2 cursor-pointer select-none text-xs text-slate-400">
                <input
                  type="checkbox"
                  checked={importantOnly}
                  onChange={(e) => setImportantOnly(e.target.checked)}
                  className="rounded border-slate-600 bg-slate-950 text-sky-500 focus:ring-sky-500 focus:ring-offset-slate-950"
                />
                Important only <span className="text-slate-600 font-normal">(signal set)</span>
              </label>
            </div>
            {signalCounts && Object.values(signalCounts).some((n) => n > 0) && (
              <div className="mb-3 flex flex-wrap gap-2 text-[10px] font-semibold uppercase tracking-wide">
                {(Object.entries(signalCounts) as [TimelineSignal, number][])
                  .filter(([, n]) => n > 0)
                  .map(([sig, n]) => {
                    const active = signalFilter === sig;
                    return (
                      <button
                        key={sig}
                        type="button"
                        onClick={() => setSignalFilter((prev) => (prev === sig ? 'all' : sig))}
                        className={`rounded border px-2 py-1 text-left transition-colors ${signalBadgeClasses(sig)} ${
                          active ? ' ring-2 ring-sky-400 ring-offset-2 ring-offset-slate-950' : ' hover:brightness-110'
                        }`}
                        title={`${n} event(s) with signal=${sig}. Click to filter; again to clear.`}
                      >
                        {signalLabel(sig)} × {n}
                      </button>
                    );
                  })}
              </div>
            )}
            {timeline.timeline.length === 0 ? (
              <div className="text-sm text-slate-500 space-y-1">
                <p>No governance events in the database for this task yet.</p>
                <p className="text-xs text-slate-600">
                  Manifests or agent activity may still exist; check the sections above. Events appear when the backend
                  emits governance audit rows.
                </p>
              </div>
            ) : filteredTimeline.length === 0 ? (
              <div className="text-sm text-slate-500 space-y-1 rounded border border-slate-800 bg-slate-950/40 px-3 py-2">
                <p>{filterEmptyMessage(signalFilter, importantOnly)}</p>
                <p className="text-xs text-slate-600">Adjust filters above or switch to “All” to see every row.</p>
              </div>
            ) : (
              <p className="text-[11px] text-slate-600 mb-2">
                Showing {filteredTimeline.length} of {timeline.timeline.length} event(s)
                {importantOnly || signalFilter !== 'all' ? ' (filtered)' : ''}.
              </p>
            )}
            {timeline.timeline.length > 0 && filteredTimeline.length > 0 ? (
              <table className="w-full text-left text-xs border-collapse min-w-[720px]">
                <thead>
                  <tr className="border-b border-slate-700 text-slate-500">
                    <th className="py-2 pr-1 w-9 font-medium text-center" scope="col" title="Expand details">
                      <span className="sr-only">Details</span>
                    </th>
                    <th className="py-2 pr-2 font-medium">ts</th>
                    <th className="py-2 pr-2 font-medium">signal</th>
                    <th className="py-2 pr-2 font-medium">phase</th>
                    <th className="py-2 pr-2 font-medium">event_type</th>
                    <th className="py-2 pr-2 font-medium">actor</th>
                    <th className="py-2 pr-2 font-medium">summary</th>
                    <th className="py-2 pr-2 font-medium">source</th>
                    <th className="py-2 pr-2 font-medium">links / ids</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTimeline.map(({ event: ev, originalIndex: i }) => {
                    const sig = parseTimelineEventSignal(ev);
                    const rowId = `gov-timeline-row-${i}`;
                    const expanded = expandedTimelineRows.has(i);
                    const detailsId = `gov-timeline-details-${i}`;
                    return (
                      <Fragment key={`${ev.ts ?? i}-${ev.payload_ref ?? i}`}>
                        <tr
                          id={rowId}
                          className={`border-b border-slate-800/80 align-top ${timelineRowClasses(sig)}${flashOutlineClass(flashAnchorId === rowId)}`}
                        >
                          <td className="py-2 pr-1 align-top text-center w-9">
                            <button
                              type="button"
                              id={`gov-timeline-expand-${i}`}
                              aria-expanded={expanded}
                              aria-controls={detailsId}
                              onClick={() => toggleTimelineRowExpand(i)}
                              className="inline-flex h-7 w-7 items-center justify-center rounded border border-slate-600 bg-slate-900 text-slate-400 hover:border-slate-500 hover:bg-slate-800 hover:text-slate-200"
                              title={expanded ? 'Hide details' : 'Show read-only details'}
                            >
                              <span className="sr-only">{expanded ? 'Collapse' : 'Expand'}</span>
                              <span aria-hidden className="text-[10px] font-bold leading-none">
                                {expanded ? '−' : '+'}
                              </span>
                            </button>
                          </td>
                          <td className="py-2 pr-2 text-slate-400 whitespace-nowrap">{ev.ts ?? '—'}</td>
                          <td className="py-2 pr-2">
                            {sig ? (
                              <span
                                className={`inline-block rounded border px-1 py-0.5 text-[9px] font-bold uppercase ${signalBadgeClasses(sig)}`}
                              >
                                {signalLabel(sig)}
                              </span>
                            ) : (
                              <span className="text-slate-600">—</span>
                            )}
                          </td>
                          <td className="py-2 pr-2 text-slate-300">{ev.phase}</td>
                          <td className="py-2 pr-2 text-slate-200">{ev.event_type}</td>
                          <td className="py-2 pr-2 text-slate-400 max-w-[120px] break-words">{formatActor(ev)}</td>
                          <td className="py-2 pr-2 text-slate-300 max-w-[200px] break-words">{ev.summary}</td>
                          <td className="py-2 pr-2 text-slate-500">{ev.source}</td>
                          <td className="py-2 pr-2 text-slate-400 break-words max-w-[240px]">
                            {formatLinksSummary(ev.links)}
                            {ev.payload_ref && !expanded ? (
                              <div className="text-slate-600 mt-0.5 font-mono text-[10px]">{ev.payload_ref}</div>
                            ) : null}
                          </td>
                        </tr>
                        {expanded ? (
                          <tr
                            className={`border-b border-slate-800/80 ${timelineRowClasses(sig)}`}
                            aria-labelledby={`gov-timeline-expand-${i}`}
                          >
                            <td colSpan={9} className="px-2 pb-3 pt-0 bg-slate-950/35 border-l-2 border-l-slate-600">
                              <TimelineExpandedDetails
                                ev={ev}
                                rowKey={String(i)}
                                copiedId={copiedId}
                                setCopiedId={setCopiedId}
                              />
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            ) : null}
          </section>
        </>
      )}

      <footer className="text-xs text-slate-600 border-t border-slate-800 pt-4">
        Read-only view; data comes from <code className="text-slate-500">GET /api/governance/resolve</code> and{' '}
        <code className="text-slate-500">GET /api/governance/tasks/…/timeline</code>. Timeline{' '}
        <code className="text-slate-500">signal</code> / <code className="text-slate-500">signal_counts</code> are
        backend-derived read-model hints, not a separate state machine. Row <strong>+</strong> expands read-only details
        from the same JSON (<code className="text-slate-500">compact_payload</code>, <code className="text-slate-500">links</code>,{' '}
        <code className="text-slate-500">payload_ref</code>) — no extra fetches. Client-side filters and jump links only change
        what is shown or scrolled to — the API response is unchanged. Empty timeline or missing agent bundle is expected
        for partial / legacy tasks — see coverage flags above. Opening the timeline URL in a new tab usually returns{' '}
        <code className="text-slate-500">401</code> without a Bearer header; use Copy and curl.
      </footer>
    </div>
  );
}
