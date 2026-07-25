'use client';

import React, { useEffect, useRef, useState } from 'react';

export type DashboardTab =
  | 'portfolio'
  | 'watchlist'
  | 'signals'
  | 'orders'
  | 'expected-take-profit'
  | 'executed-orders'
  | 'version-history'
  | 'monitoring'
  | 'jarvis'
  | 'production-diagnostics'
  | 'scheduled-investigations'
  | 'jarvis-alerts'
  | 'jarvis-daily-reports'
  | 'jarvis-analytics'
  | 'jarvis-improvement';

type PrimaryTab = {
  id: DashboardTab;
  label: string;
};

type OpsItem =
  | { kind: 'tab'; id: DashboardTab; label: string }
  | { kind: 'external'; label: string; href: string };

const PRIMARY_TABS: PrimaryTab[] = [
  { id: 'portfolio', label: 'Portfolio' },
  { id: 'watchlist', label: 'Watchlist' },
  { id: 'signals', label: 'Strategy Config' },
  { id: 'orders', label: 'Orders' },
  { id: 'expected-take-profit', label: 'Expected TP' },
  { id: 'executed-orders', label: 'Executed Orders' },
  { id: 'monitoring', label: 'Monitoring' },
];

const OPS_ITEMS: OpsItem[] = [
  { kind: 'tab', id: 'jarvis', label: 'Jarvis' },
  { kind: 'tab', id: 'jarvis-alerts', label: 'Alerts' },
  { kind: 'tab', id: 'jarvis-daily-reports', label: 'Daily Reports' },
  { kind: 'tab', id: 'jarvis-analytics', label: 'Jarvis Analytics' },
  { kind: 'tab', id: 'jarvis-improvement', label: 'Jarvis Improvement' },
  { kind: 'tab', id: 'production-diagnostics', label: 'Production Diagnostics' },
  { kind: 'tab', id: 'scheduled-investigations', label: 'Scheduled Investigations' },
  {
    kind: 'external',
    label: 'Releases (GitHub)',
    href: 'https://github.com/ccruz0/crypto-2.0/releases',
  },
];

const OPS_TAB_IDS = new Set<DashboardTab>(
  OPS_ITEMS.filter((item): item is Extract<OpsItem, { kind: 'tab' }> => item.kind === 'tab').map(
    (item) => item.id,
  ),
);

function tabButtonClass(active: boolean): string {
  return `
    px-4 py-2 text-sm font-medium transition-colors
    ${
      active
        ? 'border-b-2 border-blue-600 text-blue-600 dark:text-blue-400'
        : 'text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
    }
  `;
}

interface DashboardTabNavProps {
  activeTab: DashboardTab;
  onTabChange: (tab: DashboardTab) => void;
  unreadMonitoringCount?: number;
}

export default function DashboardTabNav({
  activeTab,
  onTabChange,
  unreadMonitoringCount = 0,
}: DashboardTabNavProps) {
  const [opsOpen, setOpsOpen] = useState(false);
  const opsRef = useRef<HTMLDivElement>(null);
  const opsActive = OPS_TAB_IDS.has(activeTab);

  useEffect(() => {
    if (!opsOpen) return;

    const onPointerDown = (event: MouseEvent) => {
      if (opsRef.current && !opsRef.current.contains(event.target as Node)) {
        setOpsOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpsOpen(false);
    };

    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [opsOpen]);

  return (
    <div className="mb-6 border-b border-gray-200 dark:border-gray-700">
      <nav className="flex flex-wrap items-end gap-2 -mb-px" aria-label="Dashboard sections">
        {PRIMARY_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => onTabChange(tab.id)}
            className={tabButtonClass(activeTab === tab.id)}
          >
            {tab.label}
            {tab.id === 'monitoring' && unreadMonitoringCount > 0 && (
              <span className="ml-2 px-2 py-0.5 text-xs bg-red-500 text-white rounded-full">
                {unreadMonitoringCount}
              </span>
            )}
          </button>
        ))}

        <div className="relative" ref={opsRef}>
          <button
            type="button"
            data-testid="ops-nav-toggle"
            aria-expanded={opsOpen}
            aria-haspopup="menu"
            onClick={() => setOpsOpen((open) => !open)}
            className={tabButtonClass(opsActive)}
          >
            Ops
            <span className="ml-1 text-xs opacity-70" aria-hidden>
              {opsOpen ? '▴' : '▾'}
            </span>
          </button>

          {opsOpen && (
            <div
              role="menu"
              data-testid="ops-nav-menu"
              className="absolute left-0 top-full z-20 mt-1 min-w-[14rem] rounded-md border border-gray-200 bg-white py-1 shadow-lg dark:border-gray-700 dark:bg-slate-800"
            >
              {OPS_ITEMS.map((item) => {
                if (item.kind === 'external') {
                  return (
                    <a
                      key={item.href}
                      role="menuitem"
                      href={item.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-slate-700"
                      onClick={() => setOpsOpen(false)}
                    >
                      {item.label}
                    </a>
                  );
                }

                const selected = activeTab === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    role="menuitem"
                    data-testid={`ops-nav-item-${item.id}`}
                    onClick={() => {
                      onTabChange(item.id);
                      setOpsOpen(false);
                    }}
                    className={`block w-full px-4 py-2 text-left text-sm ${
                      selected
                        ? 'bg-blue-50 font-medium text-blue-700 dark:bg-slate-700 dark:text-blue-300'
                        : 'text-gray-700 hover:bg-gray-50 dark:text-gray-200 dark:hover:bg-slate-700'
                    }`}
                  >
                    {item.label}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </nav>
    </div>
  );
}
