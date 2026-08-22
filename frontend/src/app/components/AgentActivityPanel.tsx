'use client';

/**
 * Panel de agentes del protocolo de revision multiangulo.
 *
 * Fuente: GET /api/agents/activity (tabla agent_activity, escrita por las
 * sesiones de revision al lanzar y cerrar cada agente).
 *
 * Naranja = trabajando ahora (fila abierta < 30 min).
 * Verde   = libre (ultima corrida cerrada).
 * Gris    = sin confirmar (fila abierta >= 30 min: la sesion murio sin cerrarla).
 *
 * Los tokens por agente NO estan disponibles (viven en la facturacion de
 * Anthropic); se muestran duracion y hallazgos en su lugar.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { getApiUrl } from '@/lib/environment';

const LABELS: Record<string, string> = {
  'atp-reglas-negocio': 'Reglas de Negocio',
  'atp-tecnico': 'Técnico',
  'atp-encaje': 'Encaje',
  'atp-economico': 'Económico',
  'atp-riesgo-despliegue': 'Riesgo de Despliegue',
  'atp-coherencia-doc': 'Coherencia Documental',
};

interface AgentCard {
  agent_name: string;
  status: 'TRABAJANDO' | 'LIBRE' | 'SIN_CONFIRMAR';
  task: string | null;
  started_at: string | null;
  finished_at: string | null;
  findings_count: number | null;
}

interface HistoryRow {
  agent_name: string;
  task: string | null;
  status: string;
  started_at: string | null;
  duration_s: number | null;
  findings_count: number | null;
  revision_id: string | null;
}

interface ActivityResponse {
  agents: AgentCard[];
  history: HistoryRow[];
  totals: { runs: number; revisions: number; findings: number; busy_now: number };
  generated_at: string;
}

const PERIODS: Array<[string, string]> = [
  ['today', 'Hoy'],
  ['week', 'Semana'],
  ['month', 'Mes'],
  ['year', 'Año'],
  ['all', 'Todo'],
];

function cardClasses(status: AgentCard['status']): string {
  if (status === 'TRABAJANDO')
    return 'bg-orange-100 border-orange-400 dark:bg-orange-900/30 dark:border-orange-600';
  if (status === 'SIN_CONFIRMAR')
    return 'bg-gray-100 border-gray-300 dark:bg-slate-700/50 dark:border-slate-600';
  return 'bg-green-50 border-green-300 dark:bg-green-900/20 dark:border-green-700';
}

function statusDot(status: AgentCard['status']): string {
  if (status === 'TRABAJANDO') return 'bg-orange-500 animate-pulse';
  if (status === 'SIN_CONFIRMAR') return 'bg-gray-400';
  return 'bg-green-500';
}

function fmtDuration(s: number | null): string {
  if (s === null || s === undefined) return '—';
  if (s < 60) return `${Math.round(s)}s`;
  return `${Math.round(s / 60)} min`;
}

export default function AgentActivityPanel() {
  const [data, setData] = useState<ActivityResponse | null>(null);
  const [period, setPeriod] = useState('week');
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const base = getApiUrl().replace(/\/$/, '');
      const res = await fetch(`${base}/agents/activity?period=${period}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'error');
    }
  }, [period]);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  const busy = (data?.totals?.busy_now ?? 0) > 0;

  return (
    <div
      className={`bg-white dark:bg-slate-800 rounded-lg shadow p-4 border-2 ${
        busy ? 'border-orange-400' : 'border-transparent'
      }`}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
          Agentes de Revisión
        </h3>
        {busy && (
          <span className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300 animate-pulse">
            revisión en curso
          </span>
        )}
      </div>

      {error && (
        <div className="text-xs text-red-600 dark:text-red-400 mb-2">
          No se pudo cargar la actividad: {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-2 mb-4">
        {(data?.agents ?? []).map((a) => (
          <div key={a.agent_name} className={`border rounded-md px-3 py-2 ${cardClasses(a.status)}`}>
            <div className="flex items-center gap-2">
              <span className={`inline-block w-2.5 h-2.5 rounded-full ${statusDot(a.status)}`} />
              <span className="font-medium text-sm text-gray-900 dark:text-white">
                {LABELS[a.agent_name] ?? a.agent_name}
              </span>
              <span className="ml-auto text-[10px] uppercase text-gray-500 dark:text-gray-400">
                {a.status === 'SIN_CONFIRMAR' ? 'sin confirmar' : a.status.toLowerCase()}
              </span>
            </div>
            {a.task && (
              <div className="mt-1 text-xs text-gray-600 dark:text-gray-300 line-clamp-2" title={a.task}>
                {a.status === 'TRABAJANDO' ? '▶ ' : 'Última: '}
                {a.task}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="flex items-center gap-1 mb-2">
        {PERIODS.map(([key, label]) => (
          <button
            key={key}
            onClick={() => setPeriod(key)}
            className={`text-xs px-2 py-1 rounded ${
              period === key
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-600 dark:bg-slate-700 dark:text-gray-300'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {data && (
        <div className="text-xs text-gray-500 dark:text-gray-400 mb-2">
          {data.totals.runs} corridas · {data.totals.revisions} revisiones ·{' '}
          {data.totals.findings} hallazgos
          <span className="ml-1 text-gray-400" title="Los tokens por agente no están disponibles: el consumo vive en la facturación de Anthropic. Se muestran duración y hallazgos.">
            · tokens n/d ⓘ
          </span>
        </div>
      )}

      <div className="max-h-64 overflow-y-auto border-t border-gray-100 dark:border-slate-700 pt-2">
        {(data?.history ?? []).length === 0 && (
          <div className="text-xs text-gray-400 py-2">Sin actividad en este periodo.</div>
        )}
        {(data?.history ?? []).map((h, i) => (
          <div key={i} className="py-1.5 border-b border-gray-50 dark:border-slate-700/50 text-xs">
            <div className="flex items-center gap-2">
              <span className="font-medium text-gray-800 dark:text-gray-200">
                {LABELS[h.agent_name] ?? h.agent_name}
              </span>
              <span className="ml-auto text-gray-400">
                {h.started_at ? new Date(h.started_at).toLocaleString() : '—'}
              </span>
            </div>
            <div className="text-gray-500 dark:text-gray-400 line-clamp-1" title={h.task ?? ''}>
              {h.task ?? '—'}
            </div>
            <div className="text-gray-400">
              {fmtDuration(h.duration_s)}
              {h.findings_count !== null ? ` · ${h.findings_count} hallazgos` : ''}
              {h.revision_id ? ` · ${h.revision_id}` : ''}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
