'use client';

import React, { useMemo, useState } from 'react';
import {
  agentStatusClass,
  buildAgentPipeline,
  formatDuration,
  type AgentPanelEntry,
} from '@/lib/jarvisAgents';
import type { JarvisExecutionTaskDetail } from '@/app/api';

function AgentCard({ agent, expanded, onToggle }: { agent: AgentPanelEntry; expanded: boolean; onToggle: () => void }) {
  return (
    <div
      data-testid={`jarvis-agent-${agent.id}`}
      className={`rounded-lg border p-3 transition-colors ${
        agent.status === 'running'
          ? 'border-blue-400 dark:border-blue-600 bg-blue-50/50 dark:bg-blue-950/20'
          : 'border-gray-200 dark:border-gray-700 bg-gray-50/50 dark:bg-slate-900/50'
      }`}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <h4 className="text-sm font-semibold text-gray-900 dark:text-white">{agent.label}</h4>
        <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold shrink-0 ${agentStatusClass(agent.status)}`}>
          {agent.status}
        </span>
      </div>

      <dl className="space-y-1 text-xs text-gray-600 dark:text-gray-400">
        <div>
          <dt className="inline font-medium text-gray-700 dark:text-gray-300">Last action: </dt>
          <dd className="inline">{agent.last_action || '—'}</dd>
        </div>
        <div className="flex flex-wrap gap-x-3">
          <span>
            <span className="font-medium text-gray-700 dark:text-gray-300">Est:</span> ${agent.estimated_cost_usd.toFixed(4)}
          </span>
          <span>
            <span className="font-medium text-gray-700 dark:text-gray-300">Actual:</span> ${agent.actual_cost_usd.toFixed(4)}
          </span>
          <span>
            <span className="font-medium text-gray-700 dark:text-gray-300">Duration:</span> {formatDuration(agent.duration_ms)}
          </span>
        </div>
      </dl>

      {agent.errors.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {agent.errors.map((err, i) => (
            <li key={i} className="text-xs text-red-600 dark:text-red-400 truncate" title={err}>
              {err}
            </li>
          ))}
        </ul>
      )}

      {agent.logs.length > 0 && (
        <button
          type="button"
          onClick={onToggle}
          className="mt-2 text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400"
        >
          {expanded ? 'Hide logs' : `Show logs (${agent.logs.length})`}
        </button>
      )}

      {expanded && agent.logs.length > 0 && (
        <ul className="mt-2 space-y-1 max-h-32 overflow-y-auto text-xs font-mono border-t border-gray-200 dark:border-gray-700 pt-2">
          {agent.logs.map((log) => (
            <li key={log.log_id || `${log.timestamp}-${log.tool}`} className="text-gray-600 dark:text-gray-400">
              <span className="text-gray-400">{log.timestamp?.slice(11, 19) || '—'}</span>{' '}
              [{log.tool}] {log.output_summary || log.input_summary}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function JarvisAgentPanel({ detail }: { detail: JarvisExecutionTaskDetail | null }) {
  const pipeline = useMemo(() => buildAgentPipeline(detail), [detail]);
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);

  return (
    <div data-testid="jarvis-agent-panel" className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-slate-800 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h3 className="font-semibold text-gray-900 dark:text-white">Multi-Agent Pipeline</h3>
        <div className="flex flex-wrap gap-2 text-xs text-gray-500">
          <span>Workflow: {pipeline.workflow_type.replace(/_/g, ' ')}</span>
          <span>·</span>
          <span>Task: {pipeline.task_status}</span>
          <span>·</span>
          <span>
            Total ${pipeline.totals.actual_cost_usd.toFixed(4)} / ${pipeline.totals.estimated_cost_usd.toFixed(4)} est
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        {pipeline.agents.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            expanded={expandedAgent === agent.id}
            onToggle={() => setExpandedAgent((prev) => (prev === agent.id ? null : agent.id))}
          />
        ))}
      </div>
    </div>
  );
}
