/**
 * Version History Tab Component
 * Extracted from page.tsx for better organization
 */

import React from 'react';

interface VersionHistoryTabProps {
  versionHistory: Array<{
    version: string;
    date: string;
    change: string;
    details: string;
  }>;
}

export default function VersionHistoryTab({ versionHistory }: VersionHistoryTabProps) {
  return (
    <div>
      <h2 className="text-xl font-semibold mb-4">Version History</h2>
      <div className="space-y-4">
        {versionHistory.map((version, index) => (
          <div key={index} className="border-b pb-4">
            <div className="flex items-center gap-4 mb-2">
              <span className="font-semibold text-blue-600">v{version.version}</span>
              <span className="text-sm text-gray-500">{version.date}</span>
            </div>
            <h3 className="font-medium mb-1">{version.change}</h3>
            <p className="text-sm text-gray-600">{version.details}</p>
          </div>
        ))}
      </div>
    </div>
  );
}



