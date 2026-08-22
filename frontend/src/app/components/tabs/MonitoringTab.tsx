/**
 * Monitoring Tab Component
 * Extracted from page.tsx for better organization
 *
 * Layout: panel principal de monitoring a la izquierda; a la derecha, el
 * panel de Agentes de Revision (protocolo multiangulo) — naranja cuando
 * hay una revision en curso, verde cuando estan libres.
 */

import React from 'react';
import MonitoringPanel from '@/app/components/MonitoringPanel';
import AgentActivityPanel from '@/app/components/AgentActivityPanel';

export default function MonitoringTab() {
  return (
    <div>
      <h2 className="text-xl font-semibold mb-4">Monitoring</h2>
      <div className="flex flex-col lg:flex-row gap-6 items-start">
        <div className="flex-1 min-w-0">
          <MonitoringPanel />
        </div>
        <div className="w-full lg:w-96 shrink-0 lg:sticky lg:top-4">
          <AgentActivityPanel />
        </div>
      </div>
    </div>
  );
}
