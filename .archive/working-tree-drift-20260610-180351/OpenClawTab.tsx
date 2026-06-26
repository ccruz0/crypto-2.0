'use client';

import React from 'react';

export default function OpenClawTab() {
  return (
    <div className="flex flex-col h-[calc(100vh-220px)] min-h-[500px]">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white">OpenClaw</h2>
        <button
          onClick={() => window.open('/openclaw/', '_blank', 'noopener,noreferrer')}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 transition-colors"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
            />
          </svg>
          Open Full Dashboard
        </button>
      </div>
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
        If the panel is blank, open the link in a new tab, sign in with Basic Auth, then refresh this page.
      </p>
      <div className="flex-1 min-h-0 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden bg-white dark:bg-gray-900">
        <iframe
          src="/openclaw/"
          title="OpenClaw UI"
          className="w-full h-full border-0"
          sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
        />
      </div>
    </div>
  );
}
