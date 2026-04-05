/**
 * Monitoring Tab Component
 * Extracted from page.tsx for better organization
 */

import React from 'react';
import MonitoringPanel from '@/app/components/MonitoringPanel';

export default function MonitoringTab() {
  return (
    <div>
      <h2 className="text-xl font-semibold mb-4">Monitoring</h2>
      <MonitoringPanel />
    </div>
  );
}



