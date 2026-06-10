'use client';

import React from 'react';
import MonitoringPanel from '@/app/components/MonitoringPanel';

export default function MonitoringPage() {
  return (
    <div className="p-4">
      <h2 className="text-xl font-semibold mb-4">Monitoring</h2>
      <p className="text-sm text-slate-500 mb-4">
        <a href="/governance/task" className="text-sky-600 dark:text-sky-400 underline">
          Governance task timeline
        </a>{' '}
        (read-only control-plane view)
      </p>
      <MonitoringPanel telegramMessages={[]} telegramMessagesLoading={false} />
    </div>
  );
}
