'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { fetchApprovalQueue, fetchSafetyStatus, type SafetyStatus } from '@/lib/jarvisApproval';

const POLL_MS = 15000;

function GateBadge({ enabled, label }: { enabled: boolean; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${
        enabled
          ? 'bg-amber-100 text-amber-900 dark:bg-amber-900/30 dark:text-amber-200'
          : 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-200'
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${enabled ? 'bg-amber-500' : 'bg-green-500'}`} />
      {label}: {enabled ? 'enabled' : 'disabled'}
    </span>
  );
}

export default function JarvisOperationalStatus() {
  const [safety, setSafety] = useState<SafetyStatus | null>(null);
  const [approvalCount, setApprovalCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const [safetyStatus, queue] = await Promise.all([fetchSafetyStatus(), fetchApprovalQueue(50)]);
        if (cancelled) return;
        setSafety(safetyStatus);
        setApprovalCount(queue.length);
        setError(null);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    };

    void load();
    const id = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const flags = safety?.phase5;
  const writeGatesDisabled =
    flags && !flags.patch_apply_enabled && !flags.pr_creation_enabled && !flags.github_write_enabled;

  return (
    <div
      data-testid="jarvis-operational-status"
      className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-slate-800 p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Operational Status</h2>
        {approvalCount > 0 && (
          <Link
            href="/jarvis/approval"
            className="text-xs font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400"
          >
            {approvalCount} pending approval{approvalCount === 1 ? '' : 's'} →
          </Link>
        )}
      </div>

      {error && <p className="text-xs text-red-600 mb-2">{error}</p>}

      <div className="flex flex-wrap gap-2 mb-3">
        {flags ? (
          <>
            <GateBadge enabled={flags.patch_apply_enabled} label="Patch apply" />
            <GateBadge enabled={flags.pr_creation_enabled} label="PR creation" />
            <GateBadge enabled={flags.github_write_enabled} label="GitHub write" />
            <GateBadge enabled={flags.double_approval_required} label="Double approval" />
          </>
        ) : (
          <span className="text-xs text-gray-500">Loading safety gates…</span>
        )}
      </div>

      {writeGatesDisabled && (
        <p className="text-xs text-green-700 dark:text-green-300 bg-green-50 dark:bg-green-900/20 rounded px-2 py-1.5">
          Write gates disabled — investigation and patch generation only; no sandbox apply or PR creation without
          explicit gate approval.
        </p>
      )}
    </div>
  );
}
