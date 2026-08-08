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
  phase5_available?: boolean;
  can_send_to_lab?: boolean;
  lab_ineligible_reason?: string;
  lab_trial_status?: string;
  lab_trial_summary?: string;
}

export interface Phase5Status {
  task_id: string;
  status: string;
  workflow_type: string;
  safety_flags: {
    patch_apply_enabled: boolean;
    pr_creation_enabled: boolean;
    github_write_enabled: boolean;
    double_approval_required: boolean;
    lab_trial_enabled?: boolean;
  };
  gate1_approved: boolean;
  gate2_approved: boolean;
  can_approve_apply: boolean;
  can_approve_pr: boolean;
  tests_passed: boolean;
  sandbox_applied: boolean;
  pr_url: string | null;
  branch_name: string | null;
  changed_files: string[];
  test_results: Record<string, unknown>;
  forbidden_check: Record<string, unknown>;
}

export interface LabTrialStatus {
  task_id: string;
  status: string;
  summary: string;
  mechanism: string;
  mechanism_label: string;
  can_send_to_lab: boolean;
  ineligible_reason: string;
  tests_passed: boolean;
  sandbox_applied: boolean;
  changed_files: string[];
  branch_name: string | null;
  test_results: Record<string, unknown>;
  error: string | null;
  can_promote: boolean;
  promote_available: boolean;
  promote_hint: string;
  safety_flags: Phase5Status['safety_flags'];
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
  phase5?: Phase5Status;
  lab_trial?: LabTrialStatus;
  plan?: Record<string, unknown>;
  error?: string | null;
  final_answer?: string | null;
  current_step?: string | null;
  approval_status?: string;
}

export interface SafetyStatus {
  phase5: Phase5Status['safety_flags'];
}

export async function fetchApprovalQueue(limit = 20): Promise<ApprovalQueueItem[]> {
  const resp = await fetch(`${API}/jarvis/approval-queue?limit=${limit}`, { cache: 'no-store' });
  if (!resp.ok) throw new Error(`approval queue failed: ${resp.status}`);
  const data = await resp.json();
  return data.items ?? [];
}

export async function fetchSafetyStatus(): Promise<SafetyStatus> {
  const resp = await fetch(`${API}/jarvis/safety-status`, { cache: 'no-store' });
  if (!resp.ok) throw new Error(`safety status failed: ${resp.status}`);
  return resp.json();
}

export async function fetchPhase5Status(taskId: string): Promise<Phase5Status> {
  const resp = await fetch(`${API}/jarvis/tasks/change/${taskId}/phase5-status`, { cache: 'no-store' });
  if (!resp.ok) throw new Error(`phase5 status failed: ${resp.status}`);
  return resp.json();
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

export async function approvePatchApply(taskId: string, actorId = 'dashboard', comment = ''): Promise<ChangeTaskDetail> {
  const resp = await fetch(`${API}/jarvis/tasks/change/${taskId}/approve-apply`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ actor_id: actorId, comment }),
  });
  if (!resp.ok) throw new Error(`approve-apply failed: ${resp.status}`);
  return resp.json();
}

export async function sendChangeTaskToLab(
  taskId: string,
  actorId = 'dashboard',
  comment = '',
): Promise<ChangeTaskDetail> {
  const resp = await fetch(`${API}/jarvis/tasks/change/${taskId}/send-to-lab`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ actor_id: actorId, comment }),
  });
  if (!resp.ok) {
    let detail = `send-to-lab failed: ${resp.status}`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return resp.json();
}

export async function fetchLabTrialStatus(taskId: string): Promise<LabTrialStatus> {
  const resp = await fetch(`${API}/jarvis/tasks/change/${taskId}/lab-status`, { cache: 'no-store' });
  if (!resp.ok) throw new Error(`lab status failed: ${resp.status}`);
  return resp.json();
}

export async function approvePrCreation(taskId: string, actorId = 'dashboard', comment = ''): Promise<ChangeTaskDetail> {
  const resp = await fetch(`${API}/jarvis/tasks/change/${taskId}/approve-pr`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ actor_id: actorId, comment }),
  });
  if (!resp.ok) throw new Error(`approve-pr failed: ${resp.status}`);
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

export function gateLabel(status: string): string {
  if (status === 'waiting_for_approval') return 'Gate 1: Apply patch in sandbox';
  if (status === 'waiting_for_pr_approval') return 'Gate 2: Create PR';
  return status;
}
