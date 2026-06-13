import { getApiUrl } from '@/lib/environment';

const API = getApiUrl();

export interface ApprovalQueueItem {
  task_id: string;
  objective: string;
  status: string;
  patch_summary: string;
  files_affected: string[];
  risk_score: number | null;
  test_results: Record<string, unknown>;
  review_findings: Array<{ dimension: string; finding: string; severity: string }>;
  approval_status: string;
  created_at: string | null;
  workflow_type: string;
}

export interface ChangeTaskDetail {
  task_id: string;
  objective: string;
  status: string;
  artifacts: Array<Record<string, unknown>>;
  review: Record<string, unknown>;
  execution_log: Array<Record<string, unknown>>;
  approvals: Array<Record<string, unknown>>;
  workflow_type: string;
}

export async function fetchApprovalQueue(limit = 20): Promise<ApprovalQueueItem[]> {
  const resp = await fetch(`${API}/jarvis/approval-queue?limit=${limit}`, { cache: 'no-store' });
  if (!resp.ok) throw new Error(`approval queue failed: ${resp.status}`);
  const data = await resp.json();
  return data.items ?? [];
}

export async function submitChangeTask(objective: string, dryRun = true): Promise<ChangeTaskDetail> {
  const resp = await fetch(`${API}/jarvis/tasks/change/submit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ objective, dry_run: dryRun, run_tests: true }),
  });
  if (!resp.ok) throw new Error(`submit failed: ${resp.status}`);
  return resp.json();
}

export async function approveChangeTask(taskId: string, actorId = 'dashboard', comment = ''): Promise<ChangeTaskDetail> {
  const resp = await fetch(`${API}/jarvis/tasks/change/${taskId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ actor_id: actorId, comment }),
  });
  if (!resp.ok) throw new Error(`approve failed: ${resp.status}`);
  return resp.json();
}

export async function rejectChangeTask(taskId: string, actorId = 'dashboard', comment = ''): Promise<ChangeTaskDetail> {
  const resp = await fetch(`${API}/jarvis/tasks/change/${taskId}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ actor_id: actorId, comment }),
  });
  if (!resp.ok) throw new Error(`reject failed: ${resp.status}`);
  return resp.json();
}

export async function fetchChangeTask(taskId: string): Promise<ChangeTaskDetail> {
  const resp = await fetch(`${API}/jarvis/tasks/change/${taskId}`, { cache: 'no-store' });
  if (!resp.ok) throw new Error(`task detail failed: ${resp.status}`);
  return resp.json();
}

export function riskBadgeClass(score: number | null): string {
  if (score == null) return 'bg-slate-700 text-slate-300';
  if (score >= 70) return 'bg-red-900/60 text-red-200';
  if (score >= 45) return 'bg-amber-900/60 text-amber-200';
  return 'bg-emerald-900/60 text-emerald-200';
}
