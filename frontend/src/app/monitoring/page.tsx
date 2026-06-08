'use client';

import React from 'react';
import MonitoringPanel from '@/app/components/MonitoringPanel';

export default function MonitoringPage() {
  return (
    <div className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-xl font-semibold">Monitoring</h2>
        <a
          href="/jarvis"
          className="px-4 py-2 text-sm border border-gray-300 dark:border-slate-600 rounded-md text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800"
        >
          Jarvis Tasks
        </a>
      </div>
      <MonitoringPanel telegramMessages={[]} telegramMessagesLoading={false} />
    </div>
  );
}
