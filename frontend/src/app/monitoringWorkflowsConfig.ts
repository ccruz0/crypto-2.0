// Static configuration for monitoring workflows
// This file is self-contained with no circular dependencies

export type MonitoringWorkflow = {
  id: string;
  title: string;
  description: string;
  apiPath: string;
};

export const MONITORING_WORKFLOWS: MonitoringWorkflow[] = [
  {
    id: 'watchlist_consistency',
    title: 'Watchlist Consistency Check',
    description: 'Compares watchlist rows against backend state.',
    apiPath: '/api/monitoring/workflows/watchlist_consistency/run',
  },
];




