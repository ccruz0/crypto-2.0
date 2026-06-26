/**
 * Read-only governance task view — client helpers (resolve + timeline APIs).
 * Token is never a new source of truth; operators supply the same Bearer used for curl.
 */

import { getApiUrl } from '@/lib/environment';

export const GOVERNANCE_TASK_VIEW_TOKEN_KEY = 'atp_governance_task_view_bearer';

export interface GovernanceResolveResponse {
  governance_task_id: string;
  notion_page_id: string | null;
  current_status: string;
  current_manifest_id: string | null;
  latest_manifest_id: string | null;
  timeline_by_task_path: string;
  timeline_by_notion_path: string | null;
  timeline_by_task_url: string | null;
  timeline_by_notion_url: string | null;
}

export interface GovernanceCoverage {
  governance_task_present: boolean;
  agent_bundle_present: boolean;
  notion_linked: boolean;
  has_manifests: boolean;
  has_events: boolean;
  timeline_scope: string;
}

export interface GovernanceManifestRow {
  manifest_id: string;
  digest?: string | null;
  digest_prefix?: string | null;
  approval_status: string;
  scope_summary?: string | null;
  risk_level?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  expires_at?: string | null;
  created_at?: string | null;
  bundle_fingerprint_prefix?: string | null;
}

export interface GovernanceAgentBundle {
  notion_task_id?: string | null;
  approval_row_status?: string | null;
  execution_status?: string | null;
  bundle_fingerprint?: string | null;
  bundle_fingerprint_prefix?: string | null;
  governance_action_class?: string | null;
  selection_reason?: string | null;
}

export type TimelineSignal = 'failed' | 'drift' | 'classification_conflict' | 'blocked';

/** Client-only timeline filter; `'all'` shows every row (subject to “important only”). */
export type TimelineSignalFilter = 'all' | TimelineSignal;

export interface GovernanceSignalCounts {
  failed: number;
  drift: number;
  classification_conflict: number;
  blocked: number;
}

export interface GovernanceTimelineEvent {
  ts: string | null;
  phase: string;
  event_type: string;
  source: string;
  summary: string;
  /** Backend-derived read-model signal (null when none). */
  signal?: TimelineSignal | null;
  links?: Record<string, unknown>;
  actor?: { type?: string; id?: string | null };
  environment?: string;
  payload_ref?: string;
  compact_payload?: Record<string, unknown>;
}

export interface GovernanceTimelineResponse {
  correlation_id: string;
  governance_task_id: string;
  notion_page_id: string | null;
  current_status: string;
  risk_level?: string | null;
  source_type?: string | null;
  source_ref?: string | null;
  current_manifest_id?: string | null;
  task_created_at?: string | null;
  task_updated_at?: string | null;
  coverage: GovernanceCoverage;
  manifests: GovernanceManifestRow[];
  agent_bundle: GovernanceAgentBundle | null;
  /** Aggregated counts of per-event `signal` (backend read model). */
  signal_counts?: GovernanceSignalCounts | null;
  timeline: GovernanceTimelineEvent[];
}

function governanceBaseUrl(): string {
  return getApiUrl().replace(/\/+$/, '');
}

function authHeader(bearer: string): HeadersInit {
  return { Authorization: `Bearer ${bearer.trim()}` };
}

/** Try resolve in fixed order: task_id → notion_page_id → manifest_id. */
export async function resolveGovernanceLookup(
  raw: string,
  bearer: string
): Promise<{ ok: true; data: GovernanceResolveResponse; tried: string } | { ok: false; status: number; detail: string; tried: string[] }> {
  const q = raw.trim();
  if (!q) {
    return { ok: false, status: 400, detail: 'Enter a governance task id, Notion page id, or manifest id.', tried: [] };
  }
  const base = governanceBaseUrl();
  const tries: { param: string; value: string; label: string }[] = [
    { param: 'task_id', value: q, label: 'task_id' },
    { param: 'notion_page_id', value: q, label: 'notion_page_id' },
    { param: 'manifest_id', value: q, label: 'manifest_id' },
  ];
  const labels: string[] = [];
  for (const t of tries) {
    labels.push(t.label);
    const url = `${base}/governance/resolve?${t.param}=${encodeURIComponent(t.value)}`;
    const res = await fetch(url, { headers: { ...authHeader(bearer) } });
    if (res.ok) {
      const data = (await res.json()) as GovernanceResolveResponse;
      return { ok: true, data, tried: t.label };
    }
    if (res.status === 404) {
      continue;
    }
    let detail = res.statusText;
    try {
      const j = (await res.json()) as { detail?: unknown };
      if (typeof j.detail === 'string') detail = j.detail;
      else if (j.detail != null) detail = JSON.stringify(j.detail);
    } catch {
      /* ignore */
    }
    return { ok: false, status: res.status, detail, tried: labels };
  }
  return {
    ok: false,
    status: 404,
    detail: 'No governance task matched this value as task_id, notion_page_id, or manifest_id.',
    tried: labels,
  };
}

export async function fetchGovernanceTimeline(
  governanceTaskId: string,
  bearer: string
): Promise<{ ok: true; data: GovernanceTimelineResponse } | { ok: false; status: number; detail: string }> {
  const base = governanceBaseUrl();
  const url = `${base}/governance/tasks/${encodeURIComponent(governanceTaskId)}/timeline`;
  const res = await fetch(url, { headers: { ...authHeader(bearer) } });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = (await res.json()) as { detail?: unknown };
      if (typeof j.detail === 'string') detail = j.detail;
    } catch {
      /* ignore */
    }
    return { ok: false, status: res.status, detail };
  }
  const data = (await res.json()) as GovernanceTimelineResponse;
  return { ok: true, data };
}

export function readStoredGovernanceBearer(): string {
  if (typeof window === 'undefined') return '';
  try {
    return (sessionStorage.getItem(GOVERNANCE_TASK_VIEW_TOKEN_KEY) || '').trim();
  } catch {
    return '';
  }
}

export function storeGovernanceBearer(token: string): void {
  if (typeof window === 'undefined') return;
  try {
    const t = token.trim();
    if (t) sessionStorage.setItem(GOVERNANCE_TASK_VIEW_TOKEN_KEY, t);
    else sessionStorage.removeItem(GOVERNANCE_TASK_VIEW_TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export function formatLinksSummary(links: Record<string, unknown> | undefined): string {
  if (!links || typeof links !== 'object') return '—';
  const parts: string[] = [];
  const order = ['manifest_id', 'manifest_digest_prefix', 'bundle_fingerprint_prefix', 'notion_page_id', 'governance_task_id'];
  for (const k of order) {
    const v = links[k];
    if (v != null && v !== '') parts.push(`${k}: ${String(v)}`);
  }
  for (const [k, v] of Object.entries(links)) {
    if (order.includes(k)) continue;
    if (v != null && v !== '') parts.push(`${k}: ${String(v)}`);
  }
  return parts.length ? parts.join(' · ') : '—';
}

/** Absolute timeline GET URL for opening/copying (browser may 401 without Bearer). */
export function governanceTimelineAbsoluteUrl(governanceTaskId: string): string {
  const base = governanceBaseUrl();
  const path = `/governance/tasks/${encodeURIComponent(governanceTaskId)}/timeline`;
  return `${base}${path}`;
}

/**
 * Notion URL: prefer task `source_ref` when it is already an https URL; else heuristic from page id.
 */
export function deriveNotionPageUrl(
  sourceRef: string | null | undefined,
  notionPageId: string | null | undefined
): string | null {
  const ref = (sourceRef || '').trim();
  if (/^https?:\/\//i.test(ref)) {
    return ref;
  }
  const nid = (notionPageId || '').trim();
  if (!nid) return null;
  const slug = nid.replace(/-/g, '');
  if (!/^[a-f0-9]{32}$/i.test(slug)) {
    return `https://www.notion.so/${encodeURIComponent(nid)}`;
  }
  return `https://www.notion.so/${slug}`;
}

const ZERO_SIGNAL_COUNTS: GovernanceSignalCounts = {
  failed: 0,
  drift: 0,
  classification_conflict: 0,
  blocked: 0,
};

/** Normalize API `signal_counts` (defaults if older server omits the field). */
export function normalizeSignalCounts(t: GovernanceTimelineResponse): GovernanceSignalCounts {
  const sc = t.signal_counts;
  if (!sc || typeof sc !== 'object') {
    return { ...ZERO_SIGNAL_COUNTS };
  }
  return {
    failed: Number(sc.failed) || 0,
    drift: Number(sc.drift) || 0,
    classification_conflict: Number(sc.classification_conflict) || 0,
    blocked: Number(sc.blocked) || 0,
  };
}

/** Use backend `signal` only (no client string-matching). */
export function parseTimelineEventSignal(ev: GovernanceTimelineEvent): TimelineSignal | null {
  const s = ev.signal;
  if (s === 'failed' || s === 'drift' || s === 'classification_conflict' || s === 'blocked') {
    return s;
  }
  return null;
}

export interface TimelineViewFilters {
  signalFilter: TimelineSignalFilter;
  /** When true, only rows with a non-null `signal` (same basis as API signal column). */
  importantOnly: boolean;
}

/** Filter timeline rows using API `signal` only; preserves original indices for scroll targets. */
export function filterTimelineForView(
  events: GovernanceTimelineEvent[],
  filters: TimelineViewFilters
): { event: GovernanceTimelineEvent; originalIndex: number }[] {
  const out: { event: GovernanceTimelineEvent; originalIndex: number }[] = [];
  events.forEach((event, originalIndex) => {
    const sig = parseTimelineEventSignal(event);
    if (filters.importantOnly && !sig) return;
    if (filters.signalFilter !== 'all' && sig !== filters.signalFilter) return;
    out.push({ event, originalIndex });
  });
  return out;
}

/** Latest matching row by array order (timeline is ascending `ts` from API → last index is most recent). */
export function findLatestTimelineIndexBySignal(
  events: GovernanceTimelineEvent[],
  signal: TimelineSignal
): number | null {
  for (let i = events.length - 1; i >= 0; i--) {
    if (parseTimelineEventSignal(events[i]) === signal) return i;
  }
  return null;
}

/** Row index of the manifest with the greatest `created_at` (ISO string compare); fallback last row. */
export function indexOfLatestManifestByCreatedAt(manifests: GovernanceManifestRow[]): number | null {
  if (!manifests.length) return null;
  let best = manifests.length - 1;
  let bestTs = '';
  for (let i = 0; i < manifests.length; i++) {
    const t = (manifests[i].created_at || '').trim();
    if (t && t >= bestTs) {
      bestTs = t;
      best = i;
    }
  }
  return best;
}

export function formatActor(ev: GovernanceTimelineEvent): string {
  const t = (ev.actor?.type || '').trim() || '—';
  const id = (ev.actor?.id || '').trim() || '—';
  if (t === '—' && id === '—') return '—';
  return `${t} · ${id}`;
}

/** Pretty JSON for timeline `compact_payload` (read-only UI); returns empty string if nothing to show. */
export function formatCompactPayloadPretty(
  compact: Record<string, unknown> | null | undefined
): string {
  if (compact == null || typeof compact !== 'object') {
    return '';
  }
  const keys = Object.keys(compact);
  if (keys.length === 0) {
    return '';
  }
  try {
    return JSON.stringify(compact, null, 2);
  } catch {
    return String(compact);
  }
}
