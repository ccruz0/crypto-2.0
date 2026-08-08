/**
 * Match Improvement recommendation cards to Jarvis tasks created via Execute,
 * and map task/LAB fields to honest plain-language trial labels.
 *
 * Execute stamps objectives as:
 *   Jarvis improvement recommendation [<id>]: <title>
 */

export const IMPROVEMENT_REC_OBJECTIVE_RE =
  /Jarvis improvement recommendation \[([^\]]+)\]:/i;

export type ImprovementTrialLabel =
  | 'Queued'
  | 'Waiting approval'
  | 'Completed'
  | 'Ready for LAB'
  | 'Testing in LAB'
  | 'LAB passed'
  | 'LAB failed'
  | 'Creating PR'
  | 'Promoted'
  | 'Failed';

export type ImprovementTrialMatch = {
  taskId: string;
  objective: string;
  taskStatus: string;
  labTrialStatus: string | null;
  canSendToLab: boolean;
  label: ImprovementTrialLabel;
};

export type ExecutionTaskLike = {
  task_id: string;
  objective: string;
  status: string;
  created_at?: string | null;
};

export type ApprovalQueueLike = {
  task_id: string;
  objective: string;
  status: string;
  can_send_to_lab?: boolean;
  lab_trial_status?: string;
  created_at?: string | null;
};

/** Extract recommendation id from an Execute objective, or null if not stamped. */
export function extractImprovementRecommendationId(objective: string | null | undefined): string | null {
  if (!objective) return null;
  const m = IMPROVEMENT_REC_OBJECTIVE_RE.exec(objective);
  return m?.[1]?.trim() || null;
}

/**
 * Map existing task + LAB fields to a plain-language label.
 * Never claims "Testing in LAB" / LAB outcomes unless real lab_trial_status says so
 * (or the task is mid apply/sandbox — which only happens after Send to LAB).
 */
export function plainImprovementTrialLabel(input: {
  taskStatus: string;
  labTrialStatus?: string | null;
  canSendToLab?: boolean;
}): ImprovementTrialLabel {
  const task = (input.taskStatus || '').toLowerCase();
  const lab = (input.labTrialStatus || '').toLowerCase();
  const canSend = Boolean(input.canSendToLab);

  // Real LAB outcomes first (Send to LAB actually happened).
  // Promoted is terminal; Creating PR is in-flight before the PR exists.
  if (lab === 'promoted') return 'Promoted';
  if (task === 'creating_pr') return 'Creating PR';
  if (lab === 'passed') return 'LAB passed';
  if (lab === 'failed' || lab === 'refused') return 'LAB failed';
  if (lab === 'testing') return 'Testing in LAB';

  // Lifecycle states that only occur after Send to LAB kicked off apply/tests.
  if (task === 'applying_patch' || task === 'sandbox_testing') return 'Testing in LAB';

  // Promote opened a PR (task may have left the approval queue; lab_trial may lag).
  if (task === 'pr_created') return 'Promoted';

  // Eligible for Send to LAB — patch trial ready, not yet started (never claim In LAB).
  if (canSend && (lab === 'not_started' || !lab)) return 'Ready for LAB';

  if (task === 'waiting_for_approval' || task === 'waiting_for_pr_approval') {
    return 'Waiting approval';
  }
  if (task === 'completed') return 'Completed';
  if (task === 'failed' || task === 'cancelled' || task === 'insufficient_evidence') return 'Failed';
  if (
    task === 'queued' ||
    task === 'planning' ||
    task === 'executing' ||
    task === 'investigating' ||
    task === 'patch_ready' ||
    task === 'reviewing' ||
    task === 'testing' ||
    task === 'running' ||
    task === 'requires_approval'
  ) {
    return 'Queued';
  }

  // Fallback: still show as queued / in-flight rather than inventing LAB progress.
  return 'Queued';
}

function createdAtMs(iso: string | null | undefined): number {
  if (!iso) return 0;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : 0;
}

/** Lab progress rank — higher = more advanced trial. */
function labRank(lab: string | null | undefined): number {
  switch ((lab || '').toLowerCase()) {
    case 'promoted':
      return 60;
    case 'passed':
      return 50;
    case 'testing':
      return 40;
    case 'failed':
    case 'refused':
      return 30;
    case 'not_started':
      return 10;
    default:
      return 0;
  }
}

function taskRank(status: string): number {
  switch ((status || '').toLowerCase()) {
    case 'pr_created':
      return 55;
    case 'creating_pr':
      return 52;
    case 'waiting_for_pr_approval':
      return 48;
    case 'sandbox_testing':
    case 'applying_patch':
      return 40;
    case 'waiting_for_approval':
      return 20;
    case 'completed':
      return 15;
    case 'failed':
      return 5;
    default:
      return 8;
  }
}

function matchScore(m: Omit<ImprovementTrialMatch, 'label'>): number {
  return labRank(m.labTrialStatus) * 1000 + taskRank(m.taskStatus) * 10;
}

/**
 * Find the best matching Execute/change task for a recommendation id.
 * Prefers the most advanced LAB/trial state; ties break to newest created_at.
 */
export function findImprovementTrialMatch(
  recommendationId: string,
  tasks: ExecutionTaskLike[],
  queue: ApprovalQueueLike[] = [],
): ImprovementTrialMatch | null {
  if (!recommendationId) return null;

  const byId = new Map<
    string,
    {
      taskId: string;
      objective: string;
      taskStatus: string;
      labTrialStatus: string | null;
      canSendToLab: boolean;
      createdAt: number;
    }
  >();

  for (const t of tasks) {
    const rid = extractImprovementRecommendationId(t.objective);
    if (rid !== recommendationId) continue;
    byId.set(t.task_id, {
      taskId: t.task_id,
      objective: t.objective,
      taskStatus: t.status,
      labTrialStatus: null,
      canSendToLab: false,
      createdAt: createdAtMs(t.created_at),
    });
  }

  for (const q of queue) {
    const rid = extractImprovementRecommendationId(q.objective);
    if (rid !== recommendationId) continue;
    const existing = byId.get(q.task_id);
    const lab = q.lab_trial_status || null;
    const canSend = Boolean(q.can_send_to_lab);
    if (existing) {
      existing.labTrialStatus = lab;
      existing.canSendToLab = canSend;
      // Prefer queue status when present (includes applying_patch / sandbox_testing).
      if (q.status) existing.taskStatus = q.status;
      existing.createdAt = Math.max(existing.createdAt, createdAtMs(q.created_at));
    } else {
      byId.set(q.task_id, {
        taskId: q.task_id,
        objective: q.objective,
        taskStatus: q.status,
        labTrialStatus: lab,
        canSendToLab: canSend,
        createdAt: createdAtMs(q.created_at),
      });
    }
  }

  if (byId.size === 0) return null;

  const ranked = [...byId.values()].sort((a, b) => {
    const scoreDiff = matchScore(b) - matchScore(a);
    if (scoreDiff !== 0) return scoreDiff;
    return b.createdAt - a.createdAt;
  });
  const best = ranked[0];
  return {
    taskId: best.taskId,
    objective: best.objective,
    taskStatus: best.taskStatus,
    labTrialStatus: best.labTrialStatus,
    canSendToLab: best.canSendToLab,
    label: plainImprovementTrialLabel({
      taskStatus: best.taskStatus,
      labTrialStatus: best.labTrialStatus,
      canSendToLab: best.canSendToLab,
    }),
  };
}

/** Build recommendationId → match map for all cards (one pass over task lists). */
export function indexImprovementTrialMatches(
  tasks: ExecutionTaskLike[],
  queue: ApprovalQueueLike[] = [],
): Map<string, ImprovementTrialMatch> {
  const ids = new Set<string>();
  for (const t of tasks) {
    const id = extractImprovementRecommendationId(t.objective);
    if (id) ids.add(id);
  }
  for (const q of queue) {
    const id = extractImprovementRecommendationId(q.objective);
    if (id) ids.add(id);
  }
  const map = new Map<string, ImprovementTrialMatch>();
  for (const id of ids) {
    const match = findImprovementTrialMatch(id, tasks, queue);
    if (match) map.set(id, match);
  }
  return map;
}
