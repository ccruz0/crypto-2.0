'use client';

import React from 'react';

export default function OpenClawPage() {
  return (
    <div className="flex flex-col h-[calc(100vh-2rem)] min-h-0">
      <div className="flex items-center justify-between gap-2 shrink-0 py-2 px-1">
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
          OpenClaw
        </h1>
        <a
          href="/openclaw/"
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
        >
          Open in new tab
        </a>
      </div>
      <div className="flex-1 min-h-0 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
        <iframe
          src="/openclaw/"
          title="OpenClaw UI"
          className="w-full h-full min-h-[400px] border-0"
          sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
        />
      </div>
    </div>
  );
}
