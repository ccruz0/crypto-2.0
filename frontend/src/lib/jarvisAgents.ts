import type { JarvisExecutionLogEntry, JarvisExecutionTaskDetail } from '@/app/api';

export type AgentPanelStatus = 'idle' | 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

export interface AgentPanelEntry {
  id: string;
  label: string;
  status: AgentPanelStatus;
  last_action: string | null;
  estimated_cost_usd: number;
  actual_cost_usd: number;
  duration_ms: number;
  errors: string[];
  logs: Array<{
    log_id?: string;
    timestamp?: string;
    tool?: string;
    input_summary?: string;
    output_summary?: string;
    duration_ms?: number;
  }>;
}

export interface AgentPipelineView {
  task_id?: string;
  workflow_type: string;
  task_status: string;
  agents: AgentPanelEntry[];
  totals: {
    estimated_cost_usd: number;
    actual_cost_usd: number;
  };
}

const AGENT_ORDER = [
  'supervisor',
  'planner',
  'repository',
  'patch',
  'reviewer',
  'test',
  'cost_guard',
] as const;

const AGENT_LABELS: Record<string, string> = {
  supervisor: 'Supervisor',
  planner: 'Planner',
  repository: 'Repository Agent',
  patch: 'Patch Agent',
  reviewer: 'Reviewer',
  test: 'Test Agent',
  cost_guard: 'Cost Guard',
};

const LOG_AGENT_MAP: Record<string, string> = {
  supervisor: 'supervisor',
  service: 'supervisor',
  planner: 'planner',
  planner_agent: 'planner',
  repository_agent: 'repository',
  patch_agent: 'patch',
  reviewer_agent: 'reviewer',
  reviewer: 'reviewer',
  test_agent: 'test',
  executor_agent: 'test',
  cost_guard: 'cost_guard',
};

const STATUS_ACTIVE_AGENT: Record<string, string> = {
  queued: 'supervisor',
  planning: 'planner',
  investigating: 'repository',
  patch_ready: 'patch',
  reviewing: 'reviewer',
  testing: 'test',
  executing: 'test',
};

const PHASE3_SKIP = new Set(['patch', 'reviewer']);

function workflowType(plan: Record<string, unknown> | undefined): string {
  if (!plan) return 'phase3_investigation';
  return plan.workflow_type === 'phase4_change' ? 'phase4_change' : 'phase3_investigation';
}

function logsForAgent(logs: JarvisExecutionLogEntry[], agentId: string): JarvisExecutionLogEntry[] {
  return logs.filter((entry) => {
    const mapped = LOG_AGENT_MAP[(entry.agent || '').toLowerCase()];
    if (mapped === agentId) return true;
    if (agentId === 'cost_guard' && (entry.tool || '').toLowerCase() === 'cost_guard') return true;
    if (agentId === 'supervisor' && (entry.agent || '').toLowerCase() === 'service') return true;
    return false;
  });
}

function lastAction(logs: JarvisExecutionLogEntry[]): string | null {
  if (!logs.length) return null;
  const last = logs[logs.length - 1];
  const tool = last.tool || '';
  const summary = last.output_summary || last.input_summary || '';
  if (tool) return `${tool}: ${summary}`.slice(0, 240);
  return summary ? String(summary).slice(0, 240) : null;
}

function totalDurationMs(logs: JarvisExecutionLogEntry[]): number {
  return logs.reduce((sum, entry) => sum + (entry.duration_ms || 0), 0);
}

function agentErrors(logs: JarvisExecutionLogEntry[], taskError?: string | null): string[] {
  const errors: string[] = [];
  for (const entry of logs) {
    const summary = String(entry.output_summary || '');
    if (summary.toUpperCase().startsWith('ERROR') || summary.toUpperCase().startsWith('FAILED')) {
      errors.push(summary.slice(0, 500));
    }
  }
  if (taskError && logs.length) errors.push(taskError.slice(0, 500));
  return errors;
}

function estimateCost(agentId: string, plan: Record<string, unknown>, totalEstimated: number): number {
  const steps = (plan.steps as Array<{ estimated_cost_usd?: number }>) || [];
  const stepCost = 0.02;
  if (!steps.length) {
    const activeCount = AGENT_ORDER.length - PHASE3_SKIP.size;
    if (PHASE3_SKIP.has(agentId)) return 0;
    return Math.round((totalEstimated / Math.max(activeCount, 1)) * 1e6) / 1e6;
  }
  if (agentId === 'planner') return stepCost;
  if (agentId === 'repository') return stepCost * 0.5;
  if (agentId === 'test') {
    const sum = steps.reduce((acc, s) => acc + (s.estimated_cost_usd || 0), 0);
    return Math.round(sum * 1e6) / 1e6;
  }
  if (agentId === 'cost_guard') return 0;
  if (agentId === 'patch' || agentId === 'reviewer') return stepCost * 2;
  return stepCost * 0.25;
}

function actualCost(agentId: string, agentLogs: JarvisExecutionLogEntry[], totalActual: number): number {
  if (!agentLogs.length || totalActual <= 0) return 0;
  if (agentId === 'test') return Math.round(totalActual * 1e6) / 1e6;
  return Math.round(totalActual * 0.1 * 1e6) / 1e6;
}

function isTerminal(status: string): boolean {
  return status === 'completed' || status === 'failed' || status === 'cancelled';
}

export function buildAgentPipeline(detail: JarvisExecutionTaskDetail | null): AgentPipelineView {
  if (!detail) {
    return {
      workflow_type: 'phase3_investigation',
      task_status: 'idle',
      agents: AGENT_ORDER.map((id) => ({
        id,
        label: AGENT_LABELS[id],
        status: 'idle',
        last_action: null,
        estimated_cost_usd: 0,
        actual_cost_usd: 0,
        duration_ms: 0,
        errors: [],
        logs: [],
      })),
      totals: { estimated_cost_usd: 0, actual_cost_usd: 0 },
    };
  }

  const status = (detail.status || 'queued').toLowerCase();
  const plan = (detail.plan || {}) as Record<string, unknown>;
  const workflow = workflowType(plan);
  const skipped = workflow === 'phase4_change' ? new Set<string>() : PHASE3_SKIP;
  const logs = detail.execution_log || [];
  const totalEstimated = detail.estimated_cost_usd ?? Number(plan.total_estimated_cost_usd) ?? 0;
  const totalActual = detail.actual_cost_usd ?? 0;
  const activeAgent = STATUS_ACTIVE_AGENT[status];
  const terminal = isTerminal(status);
  const failed = status === 'failed';

  const agents: AgentPanelEntry[] = AGENT_ORDER.map((agentId) => {
    const label = AGENT_LABELS[agentId];
    if (skipped.has(agentId)) {
      return {
        id: agentId,
        label,
        status: 'skipped',
        last_action: null,
        estimated_cost_usd: 0,
        actual_cost_usd: 0,
        duration_ms: 0,
        errors: [],
        logs: [],
      };
    }

    const agentLogs = logsForAgent(logs, agentId);
    const hasActivity = agentLogs.length > 0 || (agentId === 'planner' && Array.isArray(plan.steps) && plan.steps.length > 0);

    let agentStatus: AgentPanelStatus = 'pending';
    if (failed && activeAgent === agentId) agentStatus = 'failed';
    else if (terminal && hasActivity) agentStatus = 'completed';
    else if (activeAgent === agentId && !terminal) agentStatus = 'running';
    else if (hasActivity) agentStatus = 'completed';
    else if (status === 'waiting_for_approval' && hasActivity) agentStatus = 'completed';
    else agentStatus = 'pending';

    if (agentId === 'supervisor' && agentLogs.length && status !== 'queued') {
      agentStatus = agentStatus === 'running' ? 'running' : 'completed';
    }
    if (agentId === 'planner' && plan.steps && status !== 'queued' && status !== 'planning') {
      agentStatus = agentStatus === 'running' ? 'running' : 'completed';
    }
    if (agentId === 'cost_guard' && terminal) {
      agentStatus = failed && agentLogs.some((e) => (e.tool || '').toLowerCase() === 'cost_guard') ? 'failed' : 'completed';
    }

    return {
      id: agentId,
      label,
      status: agentStatus,
      last_action: lastAction(agentLogs),
      estimated_cost_usd: estimateCost(agentId, plan, totalEstimated),
      actual_cost_usd: actualCost(agentId, agentLogs, totalActual),
      duration_ms: totalDurationMs(agentLogs),
      errors: agentErrors(agentLogs, agentStatus === 'failed' ? detail.error : null),
      logs: agentLogs.map((entry) => ({
        log_id: entry.log_id,
        timestamp: entry.timestamp,
        tool: entry.tool,
        input_summary: entry.input_summary,
        output_summary: entry.output_summary,
        duration_ms: entry.duration_ms,
      })),
    };
  });

  return {
    task_id: detail.task_id,
    workflow_type: workflow,
    task_status: status,
    agents,
    totals: {
      estimated_cost_usd: totalEstimated,
      actual_cost_usd: totalActual,
    },
  };
}

export function formatDuration(ms: number): string {
  if (ms <= 0) return '—';
  if (ms < 1000) return `${ms}ms`;
  const sec = ms / 1000;
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const min = Math.floor(sec / 60);
  return `${min}m ${Math.round(sec % 60)}s`;
}

export function agentStatusClass(status: AgentPanelStatus): string {
  switch (status) {
    case 'running':
      return 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200';
    case 'completed':
      return 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200';
    case 'failed':
      return 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200';
    case 'skipped':
      return 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400';
    case 'pending':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200';
    default:
      return 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400';
  }
}
