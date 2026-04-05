'use client';

import React from 'react';
import MonitoringPanel from '@/app/components/MonitoringPanel';

export default function MonitoringPage() {
  return (
    <div className="p-4">
      <h2 className="text-xl font-semibold mb-4">Monitoring</h2>
      <MonitoringPanel telegramMessages={[]} telegramMessagesLoading={false} />
    </div>
  );
}
