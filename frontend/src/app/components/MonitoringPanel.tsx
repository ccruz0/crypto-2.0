'use client';

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  getMonitoringSummary,
  getSignalThrottleState,
  getWorkflows,
  restartBackend,
  MonitoringSummary,
  SignalThrottleEntry,
  TelegramMessage,
  Workflow,
} from '@/lib/api';
import { getApiUrl } from '@/lib/environment';

interface MonitoringPanelProps {
  refreshInterval?: number;
  telegramMessages: TelegramMessage[];
  telegramMessagesLoading: boolean;
  onRequestTelegramRefresh?: (options?: { silent?: boolean }) => void | Promise<void>;
}

// Simple workflow row component
function WorkflowRow({ 
  workflow, 
  isRunning, 
  message, 
  onRun 
}: { 
  workflow: Workflow; 
  isRunning: boolean;
  message: string | undefined;
  onRun: (id: string) => Promise<void>;
}) {
  // Check if workflow can be run manually (must have a non-empty run_endpoint)
  // Explicitly check for null/undefined before calling .trim() to avoid TypeError
  const canRun = workflow.run_endpoint != null && workflow.run_endpoint.trim().length > 0;
  
  const handleRun = async () => {
    if (isRunning || !canRun) return;
    try {
      await onRun(workflow.id);
    } catch (err) {
      // Error already handled in parent
    }
  };
  
  const statusColor = workflow.last_status === 'success' ? 'text-green-600' : 
                     workflow.last_status === 'error' ? 'text-red-600' : 
                     workflow.last_status === 'running' ? 'text-blue-600' : 'text-gray-600';
  
  const statusBadge = workflow.last_status === 'success' ? 'bg-green-100 text-green-800 border-green-200' :
                      workflow.last_status === 'error' ? 'bg-red-100 text-red-800 border-red-200' :
                      workflow.last_status === 'running' ? 'bg-blue-100 text-blue-800 border-blue-200' :
                      'bg-gray-100 text-gray-600 border-gray-200';

  // Format last execution time
  const formatLastExecution = (isoString: string | null | undefined): string => {
    if (!isoString) return 'Never';
    try {
      const date = new Date(isoString);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffMins = Math.floor(diffMs / 60000);
      const diffHours = Math.floor(diffMs / 3600000);
      const diffDays = Math.floor(diffMs / 86400000);
      
      if (diffMins < 1) return 'Just now';
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      if (diffDays < 7) return `${diffDays}d ago`;
      
      // For older dates, show formatted date
      return date.toLocaleString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return 'Invalid date';
    }
  };

  // Get report URL if available
  const getReportUrl = (reportPath: string | null | undefined): string | null => {
    if (!reportPath) return null;
    // If it's already a full URL, return it
    if (reportPath.startsWith('http://') || reportPath.startsWith('https://')) {
      return reportPath;
    }
    // Skip if reportPath looks like a message instead of a file path
    // Messages typically contain spaces and don't have file extensions
    if (!reportPath.includes('/') && !reportPath.includes('.md') && !reportPath.includes('.html') && !reportPath.includes('.txt')) {
      return null; // This is likely a message, not a report path
    }
    // If it's a relative path, construct URL
    // Reports are typically in docs/monitoring/, accessible via the backend
    const apiUrl = getApiUrl();
    // Remove /api suffix if present, then add the report path
    const baseUrl = apiUrl.replace(/\/api\/?$/, '');
    return `${baseUrl}/${reportPath}`;
  };

  const reportUrl = getReportUrl(workflow.last_report);
  
  // Special handling for Dashboard Data Integrity workflow
  const isDashboardDataIntegrity = workflow.id === "dashboard_data_integrity";

  return (
    <tr className="hover:bg-gray-50">
      <td className="px-4 py-3 text-sm font-medium text-gray-900">{workflow.name}</td>
      <td className="px-4 py-3 text-sm text-gray-600">{workflow.description}</td>
      <td className="px-4 py-3 text-sm text-gray-500">{workflow.schedule}</td>
      <td className="px-4 py-3">
        {isDashboardDataIntegrity ? (
          <a 
            href="/reports/dashboard-data-integrity"
            className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-800 underline"
          >
            <img 
              src="https://github.com/ccruz0/crypto-2.0/actions/workflows/dashboard-data-integrity.yml/badge.svg" 
              alt="Dashboard Data Integrity Status"
              className="h-4"
            />
          </a>
        ) : (
          <span className={`px-2 py-1 text-xs font-semibold rounded-full border ${statusBadge}`}>
            {workflow.last_status || 'unknown'}
          </span>
        )}
      </td>
      <td className="px-4 py-3 text-sm text-gray-600">
        {formatLastExecution(workflow.last_execution)}
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-col gap-2">
          {canRun ? (
            <button
              onClick={handleRun}
              disabled={isRunning}
              className="px-3 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isRunning ? 'Running...' : 'Run now'}
            </button>
          ) : (
            <span className="text-xs text-gray-400">Automated only</span>
          )}
          {isDashboardDataIntegrity ? (
            <>
              <a
                href="/reports/dashboard-data-integrity"
                className="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium rounded transition-colors text-center"
              >
                View Report
              </a>
              <a
                href="https://github.com/ccruz0/crypto-2.0/actions/workflows/dashboard-data-integrity.yml"
                target="_blank"
                rel="noopener noreferrer"
                className="px-3 py-1 bg-gray-100 text-gray-700 hover:bg-gray-200 text-xs font-medium rounded transition-colors text-center text-xs"
              >
                GitHub (Details)
              </a>
            </>
          ) : reportUrl ? (
            <a
              href={reportUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="px-3 py-1 text-xs bg-gray-100 text-gray-700 rounded hover:bg-gray-200 text-center"
            >
              Open report
            </a>
          ) : null}
        </div>
      </td>
      <td className="px-4 py-3">
        {message && (
          <span className={`text-xs ${message.startsWith('Error') ? 'text-red-600' : 'text-green-600'}`}>
            {message}
          </span>
        )}
        {workflow.last_error && (
          <span className="text-xs text-red-600 block mt-1">{workflow.last_error}</span>
        )}
      </td>
    </tr>
  );
}

export default function MonitoringPanel({
  refreshInterval = 20000,
  telegramMessages = [],
  telegramMessagesLoading = false,
  onRequestTelegramRefresh,
}: MonitoringPanelProps) {
  // All hooks must be called unconditionally before any early returns
  const [data, setData] = useState<MonitoringSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [showTelegramMessages, setShowTelegramMessages] = useState(false);
  const [coinFilter, setCoinFilter] = useState<string>('');
  const [throttleEntries, setThrottleEntries] = useState<SignalThrottleEntry[]>([]);
  const [throttleLoading, setThrottleLoading] = useState(true);
  const [throttleError, setThrottleError] = useState<string | null>(null);
  const [workflowRunning, setWorkflowRunning] = useState<Record<string, boolean>>({});
  const [workflowMessages, setWorkflowMessages] = useState<Record<string, string>>({});
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [workflowsLoading, setWorkflowsLoading] = useState(true); // Only true on initial load
  const [workflowsRefreshing, setWorkflowsRefreshing] = useState(false); // Lightweight flag for refresh indicator
  const [workflowsError, setWorkflowsError] = useState<string | null>(null); // Non-destructive error banner
  const [workflowsLastUpdate, setWorkflowsLastUpdate] = useState<Date | null>(null); // For "Updated Xs ago" label
  const workflowsFetchControllerRef = useRef<AbortController | null>(null); // Guard against overlapping polls
  const [restarting, setRestarting] = useState(false);
  const [refreshingSignals, setRefreshingSignals] = useState(false); // Track when signals are being recalculated
  const [signalsLastCalculated, setSignalsLastCalculated] = useState<Date | null>(null); // Track when signals were last calculated
  const [isFetching, setIsFetching] = useState(false); // Guard against overlapping fetches
  const fetchDataControllerRef = useRef<AbortController | null>(null); // Guard against overlapping polls
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null); // Store polling interval
  const isFetchingRef = useRef(false); // Ref to track fetching state without causing re-renders

  const fetchData = useCallback(async (forceRefresh: boolean = false) => {
    // Prevent overlapping fetches
    if (isFetchingRef.current) {
      console.log('⏭️ Skipping fetch - already in progress');
      return;
    }

    // Cancel any in-flight request
    if (fetchDataControllerRef.current) {
      fetchDataControllerRef.current.abort();
    }
    fetchDataControllerRef.current = new AbortController();

    try {
      setIsFetching(true);
      isFetchingRef.current = true;
      setError(null);
      if (forceRefresh) {
        setRefreshingSignals(true);
      }
      const summary = await getMonitoringSummary(forceRefresh);
      setData(summary);
      setLastUpdate(new Date());
      // Update signals last calculated timestamp if provided
      if (summary.signals_last_calculated) {
        try {
          setSignalsLastCalculated(new Date(summary.signals_last_calculated));
        } catch (e) {
          console.warn('Failed to parse signals_last_calculated timestamp:', e);
        }
      }
    } catch (err) {
      // Don't show error for aborted requests
      if (err instanceof Error && err.name === 'AbortError') {
        return;
      }
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      setError(errorMsg);
      console.error('Failed to fetch monitoring data:', err);
    } finally {
      setLoading(false);
      setRefreshingSignals(false);
      setIsFetching(false);
      isFetchingRef.current = false;
      fetchDataControllerRef.current = null;
    }
  }, []);
  
  const handleRefreshSignals = useCallback(async () => {
    await fetchData(true); // Force refresh signals
  }, [fetchData]);

  const fetchThrottle = useCallback(async () => {
    try {
      setThrottleError(null);
      setThrottleLoading(true);
      const entries = await getSignalThrottleState();
      setThrottleEntries(entries);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      setThrottleError(errorMsg);
      console.error('Failed to fetch signal throttle data:', err);
    } finally {
      setThrottleLoading(false);
    }
  }, []);

  const fetchWorkflows = useCallback(async (isInitialLoad: boolean = false) => {
    // Cancel any in-flight request to prevent overlapping polls
    if (workflowsFetchControllerRef.current) {
      workflowsFetchControllerRef.current.abort();
    }
    workflowsFetchControllerRef.current = new AbortController();

    try {
      // Only show loading spinner on initial load
      // For subsequent refreshes, use lightweight refreshing flag
      if (isInitialLoad) {
        setWorkflowsLoading(true);
      } else {
        setWorkflowsRefreshing(true);
      }
      setWorkflowsError(null);

      const response = await getWorkflows();
      
      // Keep last known good data: only update if we got a valid response
      // This ensures the UI never disappears during refresh
      if (response.workflows) {
        setWorkflows(response.workflows);
        setWorkflowsLastUpdate(new Date());
      }
      // If response.workflows is falsy, keep existing workflows state (last known good data)
    } catch (err) {
      // Don't clear workflows on error - keep last known good data
      // Show error as non-destructive inline banner instead
      if (!(err instanceof Error && err.name === 'AbortError')) {
        const errorMsg = err instanceof Error ? err.message : 'Unknown error';
        setWorkflowsError(errorMsg);
        console.error('Failed to fetch workflows:', err);
      }
      // workflows state remains unchanged (last known good data)
    } finally {
      setWorkflowsLoading(false);
      setWorkflowsRefreshing(false);
      workflowsFetchControllerRef.current = null;
    }
  }, []); // No dependencies - stable callback reference

  const handleRestartBackend = useCallback(async () => {
    if (restarting) return;
    
    try {
      setRestarting(true);
      await restartBackend();
      // Refresh data after a short delay to see updated status
      setTimeout(() => {
        fetchData();
      }, 2000);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      console.error('Failed to restart backend:', err);
      alert(`Error al reiniciar el backend: ${errorMsg}`);
    } finally {
      setRestarting(false);
    }
  }, [restarting, fetchData]);

  const handleRunWorkflow = useCallback(async (workflowId: string) => {
    // Note: workflows must be in dependency array, but we check it inside the function
    try {
      setWorkflowRunning(prev => ({ ...prev, [workflowId]: true }));
      setWorkflowMessages(prev => ({ ...prev, [workflowId]: '' }));
      
      const workflow = workflows.find(w => w.id === workflowId);
      if (!workflow) {
        throw new Error('Workflow not found');
      }
      
      if (!workflow.run_endpoint) {
        throw new Error('Workflow cannot be run manually');
      }
      
      // Use getApiUrl() to construct full API URL instead of relative path
      // This ensures the request goes to the correct backend URL (e.g., localhost:8002/api)
      // instead of the frontend URL (e.g., localhost:3000/api)
      const apiUrl = getApiUrl();
      const fullUrl = `${apiUrl}${workflow.run_endpoint}`;
      
      const response = await fetch(fullUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText || `HTTP ${response.status}`);
      }
      
      setWorkflowMessages(prev => ({ ...prev, [workflowId]: 'Started successfully' }));
      setTimeout(() => {
        setWorkflowMessages(prev => {
          const updated = { ...prev };
          delete updated[workflowId];
          return updated;
        });
      }, 3000);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to start workflow';
      setWorkflowMessages(prev => ({ ...prev, [workflowId]: `Error: ${errorMsg}` }));
      setTimeout(() => {
        setWorkflowMessages(prev => {
          const updated = { ...prev };
          delete updated[workflowId];
          return updated;
        });
      }, 5000);
      throw err;
    } finally {
      setWorkflowRunning(prev => ({ ...prev, [workflowId]: false }));
    }
  }, [workflows]);

  useEffect(() => {
    fetchData();
    fetchThrottle();
    fetchWorkflows(true); // Initial load

    // Auto-refresh polling every 15 seconds
    pollingIntervalRef.current = setInterval(() => {
      if (!isFetchingRef.current) {
        fetchData();
      }
    }, 15000); // 15 seconds

    // Cleanup on unmount
    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
      if (fetchDataControllerRef.current) {
        fetchDataControllerRef.current.abort();
        fetchDataControllerRef.current = null;
      }
    };

    const interval = setInterval(() => {
      fetchData();
      fetchThrottle();
      fetchWorkflows(false); // Refresh (not initial load)
    }, refreshInterval);

    return () => {
      clearInterval(interval);
      // Cancel any in-flight request on unmount
      if (workflowsFetchControllerRef.current) {
        workflowsFetchControllerRef.current.abort();
      }
    };
  }, [fetchData, fetchThrottle, fetchWorkflows, refreshInterval]);

  // Filter telegram messages by coin/symbol - must be called before any conditional logic
  // Ensure telegramMessages is always an array and coinFilter is always a string
  const safeTelegramMessages = Array.isArray(telegramMessages) ? telegramMessages : [];
  const safeCoinFilter = typeof coinFilter === 'string' ? coinFilter : '';
  const filteredTelegramMessages = useMemo(() => {
    const trimmedFilter = safeCoinFilter.trim();
    if (!trimmedFilter) {
      return safeTelegramMessages;
    }
    const filterUpper = trimmedFilter.toUpperCase();
    return safeTelegramMessages.filter(msg => {
      if (!msg || !msg.symbol) return false;
      return msg.symbol.toUpperCase().includes(filterUpper);
    });
  }, [safeTelegramMessages, safeCoinFilter]);

  const formatTimestamp = (ts: string): string => {
    try {
      const date = new Date(ts);
      if (isNaN(date.getTime())) return ts;
      return date.toLocaleString(undefined, {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
        timeZoneName: 'short'
      });
    } catch {
      return ts;
    }
  };

  const formatDuration = (seconds: number | null): string => {
    if (seconds === null) return 'N/A';
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  };

  const formatRelativeTime = (seconds?: number | null): string => {
    if (seconds === null || seconds === undefined) return 'N/A';
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) {
      const mins = Math.floor(seconds / 60);
      return `${mins}m ago`;
    }
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${mins}m ago`;
  };

  const getHealthColor = (health: string): string => {
    switch (health) {
      case 'healthy':
        return 'bg-green-100 text-green-800 border-green-300';
      case 'degraded':
        return 'bg-yellow-100 text-yellow-800 border-yellow-300';
      case 'unhealthy':
      case 'error':
        return 'bg-red-100 text-red-800 border-red-300';
      default:
        return 'bg-gray-100 text-gray-800 border-gray-300';
    }
  };

  const getThrottleStatusStyles = (status: string): string => {
    switch (status.toUpperCase()) {
      case 'BLOCKED':
        return 'bg-red-100 text-red-800 border-red-200';
      case 'SENT':
        return 'bg-green-100 text-green-800 border-green-200';
      case 'ORDER SKIPPED':
        return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      default:
        return 'bg-gray-100 text-gray-700 border-gray-200';
    }
  };

  const renderSideBadge = (side: string) => {
    const isBuy = side?.toUpperCase() === 'BUY';
    const classes = isBuy
      ? 'bg-green-100 text-green-800 border-green-200'
      : 'bg-red-100 text-red-800 border-red-200';
    return (
      <span className={`px-2 py-0.5 text-xs font-semibold rounded-full border ${classes}`}>
        {side?.toUpperCase()}
      </span>
    );
  };

  const formatStrategyKey = (key: string): string => {
    if (!key) return 'N/A';
    const [strategy, approach] = key.split(':');
    const formatPart = (part?: string) =>
      part ? part.replace(/_/g, ' ').replace(/\b\w/g, char => char.toUpperCase()) : '';
    const parts = [formatPart(strategy), formatPart(approach)];
    const validParts: string[] = [];
    for (let i = 0; i < parts.length; i++) {
      if (parts[i]) validParts.push(parts[i]);
    }
    return validParts.join(' / ') || key;
  };

  const formatEmitReason = (reason: string | null | undefined): string => {
    if (!reason) return '—';
    
    const reasonLower = reason.toLowerCase();
    
    // First alert
    if (reasonLower.includes('no previous') || reasonLower.includes('first signal')) {
      return '🆕 First alert';
    }
    
    // Parameter change
    if (reasonLower.includes('parameter changed:')) {
      // Extract the parameter name(s) from the reason
      const paramMatch = reason.match(/parameter changed:\s*(.+)/i);
      if (paramMatch) {
        return `⚙️ Parameter changed: ${paramMatch[1]}`;
      }
      return '⚙️ Parameter changed';
    }
    
    // Strategy change / Force reset
    if (reasonLower.includes('forced_after_toggle_reset') || reasonLower.includes('forced')) {
      return '🔄 Strategy changed / Manual reset';
    }
    
    // Side change
    if (reasonLower.includes('opposite-side') || reasonLower.includes('side change')) {
      if (reasonLower.includes('sell') && reasonLower.includes('buy')) {
        return '🔄 Side change (SELL→BUY)';
      } else if (reasonLower.includes('buy') && reasonLower.includes('sell')) {
        return '🔄 Side change (BUY→SELL)';
      }
      return '🔄 Side change';
    }
    
    // Blocked
    if (reasonLower.includes('blocked') || reasonLower.includes('throttled')) {
      if (reasonLower.includes('min_time')) {
        return '⏸️ Throttled: Cooldown';
      }
      if (reasonLower.includes('min_change')) {
        return '⏸️ Throttled: Price change';
      }
      return '⏸️ Throttled';
    }
    
    // Price change and/or time elapsed
    if (reason.includes('Δt=') || reason.includes('|Δp|=')) {
      const parts: string[] = [];
      // Extract time info
      const timeMatch = reason.match(/Δt=([\d.]+)m/);
      if (timeMatch) {
        const elapsed = parseFloat(timeMatch[1]);
        parts.push(`⏱️ Cooldown (${elapsed.toFixed(1)}m)`);
      }
      // Extract price change info
      const priceMatch = reason.match(/\|Δp\|=([↑↓→]?)\s*([\d.]+)%/);
      if (priceMatch) {
        const direction = priceMatch[1] || '→';
        const changePct = parseFloat(priceMatch[2]);
        const directionEmoji = direction === '↑' ? '↑' : direction === '↓' ? '↓' : '→';
        parts.push(`💹 Price change (${directionEmoji}${changePct.toFixed(2)}%)`);
      }
      if (parts.length > 0) {
        return parts.join(' | ');
      }
    }
    
    // No previous limits
    if (reasonLower.includes('no previous limits')) {
      return '✅ No limits configured';
    }
    
    // Default: simplify the reason
    return reason
      .replace(/THROTTLED_/g, '')
      .replace(/_/g, ' ')
      .replace(/\b\w/g, char => char.toUpperCase())
      .substring(0, 60); // Limit length
  };

  const getSeverityColor = (severity: string): string => {
    switch (severity.toUpperCase()) {
      case 'ERROR':
        return 'bg-red-100 text-red-800 border-red-300';
      case 'WARNING':
        return 'bg-yellow-100 text-yellow-800 border-yellow-300';
      case 'INFO':
        return 'bg-blue-100 text-blue-800 border-blue-300';
      default:
        return 'bg-gray-100 text-gray-800 border-gray-300';
    }
  };

  // Helper to format backend UTC timestamps robustly
  const formatBackendUtcTimestamp = (ts: string | null | undefined): string | null => {
    if (!ts) return null;
    const raw = String(ts).trim();
    if (!raw) return null;

    // Normalize known backend edge cases and formats.
    let normalized = raw;
    // Fix invalid "+00:00Z" suffix if present.
    if (normalized.endsWith("+00:00Z")) {
      normalized = normalized.replace("+00:00Z", "Z");
    }
    // If backend returns `YYYY-MM-DD HH:MM:SS` (no T / timezone), normalize to ISO UTC.
    if (!normalized.includes('T') && normalized.includes(' ')) {
      normalized = normalized.replace(' ', 'T');
    }
    // If there is no timezone designator, assume UTC.
    if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(normalized)) {
      normalized = `${normalized}Z`;
    }

    const d = new Date(normalized);
    if (isNaN(d.getTime())) return null;

    const formatted = d.toLocaleString(undefined, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
      timeZoneName: 'short',
    });

    // Harden: if formatted result contains "Invalid Date", return null
    if (formatted && formatted.toLowerCase().includes('invalid date')) {
      return null;
    }

    return formatted;
  };

  // Early returns AFTER all hooks but BEFORE data processing
  // This ensures all hooks are called consistently while allowing early exit for loading/error states
  if (loading && !data) {
    return (
      <div className="py-8 text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
        <p className="text-gray-500">Loading monitoring data...</p>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="text-center py-8 text-red-500">
        <p>Error loading monitoring data: {error}</p>
        <button
          onClick={() => fetchData(false)}
          className="mt-4 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
        >
          Retry
        </button>
      </div>
    );
  }

  // Ensure all arrays are initialized to prevent initialization errors
  // Use defensive programming to handle any data structure issues
  let monitoringData;
  try {
    monitoringData = data ? {
      ...data,
      window_minutes: data.window_minutes ?? null,
      generated_at_utc: data.generated_at_utc ?? null,
      errors: Array.isArray(data.errors) ? data.errors : [],
      alerts: Array.isArray(data.alerts) ? data.alerts : [],
      active_alerts: typeof data.active_alerts === 'number' ? data.active_alerts : 0,
      backend_health: typeof data.backend_health === 'string' ? data.backend_health : 'error',
      last_sync_seconds: data.last_sync_seconds ?? null,
      portfolio_state_duration: typeof data.portfolio_state_duration === 'number' ? data.portfolio_state_duration : 0,
      open_orders: typeof data.open_orders === 'number' ? data.open_orders : 0,
      balances: typeof data.balances === 'number' ? data.balances : 0,
      scheduler_ticks: typeof data.scheduler_ticks === 'number' ? data.scheduler_ticks : 0,
      last_backend_restart: data.last_backend_restart ?? null,
      backend_restart_status: data.backend_restart_status ?? null,
      backend_restart_timestamp: data.backend_restart_timestamp ?? null,
    } : {
      active_alerts: 0,
      backend_health: 'error',
      last_sync_seconds: null,
      portfolio_state_duration: 0,
      open_orders: 0,
      balances: 0,
      scheduler_ticks: 0,
      errors: [],
      last_backend_restart: null,
      backend_restart_status: null,
      backend_restart_timestamp: null,
      alerts: []
    };
  } catch (err) {
    console.error('Error processing monitoring data:', err);
    monitoringData = {
      active_alerts: 0,
      backend_health: 'error',
      last_sync_seconds: null,
      portfolio_state_duration: 0,
      open_orders: 0,
      balances: 0,
      scheduler_ticks: 0,
      errors: [],
      last_backend_restart: null,
      backend_restart_status: null,
      backend_restart_timestamp: null,
      alerts: []
    };
  }

  // Build error items array
  const errorItems: React.ReactNode[] = [];
  if (Array.isArray(monitoringData.errors) && monitoringData.errors.length > 0) {
    for (let idx = 0; idx < monitoringData.errors.length; idx++) {
      errorItems.push(<li key={idx} className="text-sm text-red-700">{monitoringData.errors[idx]}</li>);
    }
  }

  // Build alert rows array
  const alertRows: React.ReactNode[] = [];
  if (Array.isArray(monitoringData.alerts) && monitoringData.alerts.length > 0) {
    for (let idx = 0; idx < monitoringData.alerts.length; idx++) {
      const alert = monitoringData.alerts[idx];
      // Use status_label if available (from backend fix), otherwise fallback to alert_status
      const status = alert.status_label || alert.alert_status || (alert.decision_type === 'FAILED' ? 'FAILED' : 'BLOCKED');
      
      // Status badge colors
      const getStatusBadgeColor = (status: string) => {
        if (status === 'SENT') return 'bg-green-100 text-green-800 border-green-200';
        if (status === 'FAILED') return 'bg-red-100 text-red-800 border-red-200';
        if (status === 'BLOCKED') return 'bg-yellow-100 text-yellow-800 border-yellow-200';
        return 'bg-gray-100 text-gray-800 border-gray-200';
      };
      
      alertRows.push(
        <tr key={idx} className="hover:bg-gray-50">
          <td className="px-4 py-3 text-sm text-gray-900">{alert.type}</td>
          <td className="px-4 py-3 text-sm font-medium text-gray-900">{alert.symbol}</td>
          <td className="px-4 py-3">
            <span className={`px-2 py-1 text-xs font-semibold rounded border ${getStatusBadgeColor(status)}`}>
              {status}
            </span>
            {alert.reason_code && status !== 'SENT' && (
              <div className="mt-1">
                <code className="px-1.5 py-0.5 text-xs bg-gray-200 text-gray-700 rounded">{alert.reason_code}</code>
              </div>
            )}
          </td>
          <td className="px-4 py-3 text-sm text-gray-700">
            {/* Show reason_code/reason_message when status != SENT */}
            {status !== 'SENT' && (alert.reason_code || alert.reason_message) ? (
              <div>
                {alert.reason_message && (
                  <div className="text-gray-700">{alert.reason_message}</div>
                )}
                {!alert.reason_message && alert.reason_code && (
                  <div className="text-gray-600">{alert.reason_code}</div>
                )}
              </div>
            ) : (
              <span className="text-gray-500">Signal sent successfully</span>
            )}
          </td>
          <td className="px-4 py-3 text-sm text-gray-500">{formatTimestamp(alert.timestamp)}</td>
        </tr>
      );
    }
  }

  // Component for expandable message dropdown
  const MessageDropdown = ({ entry, idx }: { entry: SignalThrottleEntry; idx: number }) => {
    const [isOpen, setIsOpen] = useState(false);
    // Use telegram_message if available (full message), otherwise fallback to emit_reason
    const fullMessage = entry.telegram_message || entry.emit_reason || 'No message available';
    const displayText = formatEmitReason(entry.emit_reason);
    const isTruncated = fullMessage.length > 60 || fullMessage !== displayText || entry.telegram_message !== undefined;

    return (
      <td className="px-4 py-3 text-sm text-gray-600 max-w-xs">
        <div className="relative">
          <button
            onClick={() => setIsOpen(!isOpen)}
            className="flex items-center gap-1 text-left w-full hover:text-blue-600 transition-colors group"
            title={isTruncated ? 'Click to view full message' : undefined}
          >
            <span className="block truncate flex-1">{displayText}</span>
            {isTruncated && (
              <span className="flex-shrink-0 text-blue-500 text-xs group-hover:text-blue-700">
                {isOpen ? '▼' : '▶'}
              </span>
            )}
          </button>
          {isOpen && (
            <>
              {/* Backdrop to close on outside click */}
              <div 
                className="fixed inset-0 z-40" 
                onClick={() => setIsOpen(false)}
              />
              {/* Dropdown content */}
              <div className="absolute z-50 mt-1 left-0 w-96 bg-white border border-gray-300 rounded-lg shadow-xl p-3 max-h-64 overflow-y-auto">
                <div className="flex justify-between items-start mb-2">
                  <span className="text-xs font-semibold text-gray-700">Mensaje completo de Telegram:</span>
                  <button
                    onClick={() => setIsOpen(false)}
                    className="text-gray-400 hover:text-gray-600 text-xs font-bold"
                    title="Cerrar"
                  >
                    ✕
                  </button>
                </div>
                <div className="text-sm text-gray-800 whitespace-pre-wrap break-words">
                  {fullMessage}
                </div>
              </div>
            </>
          )}
        </div>
      </td>
    );
  };

  // Build throttle rows array - limit to last 5 orders
  const throttleRows: React.ReactNode[] = [];
  if (Array.isArray(throttleEntries) && throttleEntries.length > 0) {
    const limitedEntries = throttleEntries.slice(0, 5);
    for (let idx = 0; idx < limitedEntries.length; idx++) {
      const entry = limitedEntries[idx];
      const priceChangeDisplay = entry.price_change_pct != null 
        ? `${entry.price_change_pct >= 0 ? '+' : ''}${entry.price_change_pct.toFixed(2)}%`
        : '—';
      const priceChangeColor = entry.price_change_pct != null
        ? entry.price_change_pct >= 0 
          ? 'text-green-600' 
          : 'text-red-600'
        : 'text-gray-500';
      throttleRows.push(
        <tr key={`${entry.symbol}-${entry.strategy_key}-${entry.side}-${idx}`} className="hover:bg-gray-50">
          <td className="px-4 py-3 text-sm font-semibold text-gray-900">{entry.symbol}</td>
          <td className="px-4 py-3 text-sm text-gray-700">
            {formatStrategyKey(entry.strategy_key)}
          </td>
          <td className="px-4 py-3 text-sm">{renderSideBadge(entry.side)}</td>
          <td className="px-4 py-3 text-sm text-gray-700">
            {entry.last_price != null ? `$${entry.last_price.toFixed(4)}` : '—'}
          </td>
          <td className={`px-4 py-3 text-sm font-medium ${priceChangeColor}`}>
            {priceChangeDisplay}
          </td>
          <MessageDropdown entry={entry} idx={idx} />
          <td className="px-4 py-3 text-sm text-gray-600">
            {entry.last_time ? formatTimestamp(entry.last_time) : 'N/A'}
          </td>
          <td className="px-4 py-3 text-sm text-gray-600">
            {formatRelativeTime(entry.seconds_since_last)}
          </td>
        </tr>
      );
    }
  }

  // Build workflow rows array from API-fetched workflows
  const workflowRows: React.ReactNode[] = [];
  for (let idx = 0; idx < workflows.length; idx++) {
    const workflow = workflows[idx];
    if (!workflow || !workflow.id) continue;
    workflowRows.push(
      <WorkflowRow
        key={workflow.id}
        workflow={workflow}
        isRunning={workflowRunning[workflow.id] || false}
        message={workflowMessages[workflow.id]}
        onRun={handleRunWorkflow}
      />
    );
  }

  // Helper function to determine text color based on message content
  const getMessageTextColor = (message: string, orderSkipped: boolean, blocked: boolean): string => {
    const upperMessage = message.toUpperCase();
    
    // Check for SELL signals and orders (red) - more comprehensive matching
    if (upperMessage.includes('SELL SIGNAL') || 
        upperMessage.includes('SELL ORDER') || 
        upperMessage.includes('🔴 SELL') ||
        (upperMessage.includes('SELL') && (upperMessage.includes('SIGNAL') || upperMessage.includes('ORDER') || upperMessage.includes('DETECTED')))) {
      return 'text-red-600 font-medium';
    }
    
    // Check for BUY signals and orders (green) - more comprehensive matching
    if (upperMessage.includes('BUY SIGNAL') || 
        upperMessage.includes('BUY ORDER') || 
        upperMessage.includes('🟢 BUY') ||
        (upperMessage.includes('BUY') && (upperMessage.includes('SIGNAL') || upperMessage.includes('ORDER') || upperMessage.includes('DETECTED')))) {
      return 'text-green-600 font-medium';
    }
    
    // Default colors based on status
    if (orderSkipped) {
      return 'text-yellow-800 font-medium';
    }
    if (blocked) {
      return 'text-gray-600 italic';
    }
    return 'text-blue-700 font-medium';
  };

  // Component for expandable decision details
  const DecisionDetailsDropdown = ({ msg, idx }: { msg: TelegramMessage; idx: number }) => {
    const [isOpen, setIsOpen] = useState(false);
    const hasDetails = !!(msg.decision_type || msg.reason_code || msg.reason_message || msg.context_json || msg.exchange_error_snippet);
    
    if (!hasDetails) return null;
    
    return (
      <div className="mt-2">
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="text-xs text-blue-600 hover:text-blue-800 underline flex items-center gap-1"
        >
          <span>{isOpen ? 'Hide' : 'Show'} Details</span>
          <span className="text-xs">{isOpen ? '▼' : '▶'}</span>
        </button>
        {isOpen && (
          <div className="mt-2 p-3 bg-gray-50 border border-gray-200 rounded-lg text-xs space-y-2">
            {msg.decision_type && (
              <div>
                <span className="font-semibold text-gray-700">Decision:</span>{' '}
                <span className={`px-2 py-0.5 rounded ${
                  msg.decision_type === 'FAILED' 
                    ? 'bg-red-100 text-red-800' 
                    : 'bg-yellow-100 text-yellow-800'
                }`}>
                  {msg.decision_type}
                </span>
              </div>
            )}
            {msg.reason_code && (
              <div>
                <span className="font-semibold text-gray-700">Reason Code:</span>{' '}
                <code className="px-2 py-0.5 bg-gray-200 rounded text-gray-800">{msg.reason_code}</code>
              </div>
            )}
            {msg.reason_message && (
              <div>
                <span className="font-semibold text-gray-700">Reason:</span>{' '}
                <span className="text-gray-700">{msg.reason_message}</span>
              </div>
            )}
            {msg.exchange_error_snippet && (
              <div>
                <span className="font-semibold text-red-700">Exchange Error:</span>
                <pre className="mt-1 p-2 bg-red-50 border border-red-200 rounded text-red-800 whitespace-pre-wrap break-words max-h-32 overflow-y-auto">
                  {msg.exchange_error_snippet}
                </pre>
              </div>
            )}
            {msg.context_json && (
              <div>
                <span className="font-semibold text-gray-700">Context:</span>
                <pre className="mt-1 p-2 bg-gray-100 border border-gray-300 rounded text-gray-700 whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
                  {JSON.stringify(msg.context_json, null, 2)}
                </pre>
              </div>
            )}
            {msg.correlation_id && (
              <div>
                <span className="font-semibold text-gray-700">Correlation ID:</span>{' '}
                <code className="px-2 py-0.5 bg-gray-200 rounded text-gray-600 text-xs">{msg.correlation_id}</code>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  // Build telegram message items array
  const telegramItems: React.ReactNode[] = [];
  try {
    if (Array.isArray(filteredTelegramMessages) && filteredTelegramMessages.length > 0) {
      for (let idx = 0; idx < filteredTelegramMessages.length; idx++) {
        const msg = filteredTelegramMessages[idx];
        if (!msg) continue;
        // Determine status label: decision_type takes precedence, then order_skipped, then blocked
        let statusLabel: string;
        let decisionBadge: React.ReactNode | null = null;
        if (msg.decision_type) {
          statusLabel = msg.decision_type;
          decisionBadge = (
            <span
              className={`px-2 py-0.5 text-xs font-semibold rounded-full border ${
                msg.decision_type === 'FAILED'
                  ? 'bg-red-100 text-red-800 border-red-200'
                  : 'bg-yellow-100 text-yellow-800 border-yellow-200'
              }`}
            >
              {msg.decision_type}
            </span>
          );
        } else if (msg.order_skipped) {
          statusLabel = 'ORDER SKIPPED';
        } else if (msg.throttle_status) {
          statusLabel = msg.throttle_status.toUpperCase();
        } else if (msg.blocked) {
          statusLabel = 'BLOCKED';
        } else {
          statusLabel = 'SENT';
        }
        // Background color: FAILED gets red tint, SKIPPED gets yellow/orange, blocked gets gray, sent gets blue
        const bgColor = msg.decision_type === 'FAILED'
          ? 'bg-red-50 border-red-200'
          : msg.decision_type === 'SKIPPED' || msg.order_skipped
          ? 'bg-yellow-50 border-yellow-200'
          : msg.blocked
          ? 'bg-gray-50 border-gray-200'
          : 'bg-blue-50 border-blue-200';
        telegramItems.push(
          <div
            key={idx}
            className={`p-4 border ${bgColor}`}
          >
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <p
                  className={`text-sm ${getMessageTextColor(msg.message || '', msg.order_skipped || false, msg.blocked || false)}`}
                >
                  {msg.message}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {decisionBadge || (
                    <span
                      className={`px-2 py-0.5 text-xs font-semibold rounded-full border ${
                        msg.order_skipped
                          ? 'bg-yellow-100 text-yellow-800 border-yellow-200'
                          : getThrottleStatusStyles(statusLabel)
                      }`}
                    >
                      {statusLabel}
                    </span>
                  )}
                  {msg.reason_code && (
                    <code className="px-2 py-0.5 text-xs bg-gray-200 text-gray-700 rounded">
                      {msg.reason_code}
                    </code>
                  )}
                  {msg.symbol && (
                    <span className="text-xs text-gray-600 font-medium">{msg.symbol}</span>
                  )}
                </div>
                {msg.reason_message && (
                  <p
                    className="text-xs text-gray-700 mt-1 font-medium"
                    title={msg.reason_message}
                  >
                    {msg.reason_message}
                  </p>
                )}
                {msg.throttle_reason && !msg.reason_message && (
                  <p
                    className="text-xs text-gray-500 mt-1 line-clamp-2"
                    title={msg.throttle_reason}
                  >
                    {msg.throttle_reason}
                  </p>
                )}
                <DecisionDetailsDropdown msg={msg} idx={idx} />
              </div>
              <div className="ml-4 text-xs text-gray-400">
                {formatTimestamp(msg.timestamp)}
              </div>
            </div>
          </div>
        );
      }
    }
  } catch (err) {
    console.error('Error building telegram items:', err);
  }

  return (
    <div>
      <div className="mb-4 flex justify-between items-center">
        {lastUpdate && (
          <div className="text-sm text-gray-500">
            <span className="mr-2">🕐</span>
            Last updated: {lastUpdate.toLocaleString(undefined, {
              year: 'numeric',
              month: '2-digit',
              day: '2-digit',
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
              hour12: true,
              timeZoneName: 'short'
            })}
          </div>
        )}
        <button
          onClick={() => fetchData(false)}
          className="px-3 py-1 text-sm bg-gray-100 text-gray-700 rounded hover:bg-gray-200"
          disabled={loading}
        >
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {/* Health Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <div className="bg-white rounded-lg shadow p-4 border border-gray-200">
          <div className="text-sm text-gray-500 mb-1">Backend Health</div>
          <div className={`text-lg font-semibold px-3 py-1 rounded border inline-block ${getHealthColor(monitoringData.backend_health)}`}>
            {monitoringData.backend_health.toUpperCase()}
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-4 border border-gray-200">
          <div className="text-sm text-gray-500 mb-1">Portfolio State Duration</div>
          <div className="text-2xl font-bold text-gray-800">
            {monitoringData.portfolio_state_duration.toFixed(2)}s
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-4 border border-gray-200">
          <div className="text-sm text-gray-500 mb-1">Last Sync</div>
          <div className="text-sm font-semibold text-gray-800">
            {formatDuration(monitoringData.last_sync_seconds)}
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-4 border border-gray-200">
          <div className="text-sm text-gray-500 mb-1">Active Alerts</div>
          <div className="text-2xl font-bold text-gray-800">
            {monitoringData.active_alerts}
          </div>
          <div className="text-xs text-gray-400 mt-1">Events (Telegram/throttle)</div>
        </div>

        <div className="bg-white rounded-lg shadow p-4 border border-gray-200">
          <div className="text-sm text-gray-500 mb-1">Active Signals</div>
          <div className="text-2xl font-bold text-gray-800">
            {(monitoringData.active_signals_count ?? 0)}
          </div>
          <div className="text-xs text-gray-400 mt-1">Current state (not events)</div>
        </div>

        <div className="bg-white rounded-lg shadow p-4 border border-gray-200">
          <div className="text-sm text-gray-500 mb-1">Open Orders</div>
          <div className="text-2xl font-bold text-gray-800">
            {monitoringData.open_orders}
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-4 border border-gray-200">
          <div className="text-sm text-gray-500 mb-1">Balances</div>
          <div className="text-2xl font-bold text-gray-800">
            {monitoringData.balances}
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-4 border border-gray-200">
          <div className="text-sm text-gray-500 mb-1">Scheduler Cycles</div>
          <div className="text-2xl font-bold text-gray-800">
            {monitoringData.scheduler_ticks.toLocaleString()}
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-4 border border-gray-200">
          <div className="text-sm text-gray-500 mb-1">Backend Restart</div>
          <div className="text-sm font-semibold text-gray-800 mb-2">
            {monitoringData.last_backend_restart
              ? formatDuration(Math.floor((Date.now() / 1000) - monitoringData.last_backend_restart))
              : 'N/A'}
          </div>
          {monitoringData.backend_restart_status && (
            <div className={`text-xs font-semibold px-2 py-1 rounded border mb-2 ${
              monitoringData.backend_restart_status === 'restarting' 
                ? 'bg-blue-100 text-blue-800 border-blue-200'
                : monitoringData.backend_restart_status === 'restarted'
                ? 'bg-green-100 text-green-800 border-green-200'
                : 'bg-red-100 text-red-800 border-red-200'
            }`}>
              {monitoringData.backend_restart_status === 'restarting' ? '🔄 Reiniciando...' :
               monitoringData.backend_restart_status === 'restarted' ? '✅ Reiniciado' :
               '❌ Error'}
            </div>
          )}
          <button
            onClick={handleRestartBackend}
            disabled={restarting || monitoringData.backend_restart_status === 'restarting'}
            className="w-full px-3 py-1.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {restarting || monitoringData.backend_restart_status === 'restarting' ? 'Reiniciando...' : 'Reiniciar Backend'}
          </button>
        </div>
      </div>

      {/* Errors Section */}
      {errorItems.length > 0 && (
        <div className="mb-6 bg-red-50 border border-red-200 rounded-lg p-4">
          <h3 className="text-lg font-semibold text-red-800 mb-2">Errors</h3>
          <ul className="list-disc list-inside space-y-1">
            {errorItems}
          </ul>
        </div>
      )}

      {/* Alerts Table */}
      <div className="bg-white rounded-lg shadow border border-gray-200 mb-6">
        <div className="p-4 border-b border-gray-200 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h3 className="text-lg font-semibold">Active Alerts</h3>
            {refreshingSignals && (
              <div className="flex items-center gap-2 text-sm text-blue-600">
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600"></div>
                <span>Recalculating signals...</span>
              </div>
            )}
            <div className="text-xs text-gray-500" data-testid="monitor-last-updated">
              {(() => {
                const ts = (data?.generated_at_utc ?? monitoringData?.generated_at_utc) as any;
                const formatted = formatBackendUtcTimestamp(ts);
                // Never show "Invalid Date" - show "—" if missing or invalid
                const safe = (formatted && !formatted.toLowerCase().includes('invalid date')) 
                  ? formatted 
                  : '—';
                return <>Last updated: {safe}</>;
              })()}
            </div>
            <div className="text-xs text-gray-500" data-testid="monitor-window">
              {data?.window_minutes || monitoringData?.window_minutes ? (
                <>Window: {data?.window_minutes || monitoringData?.window_minutes} min</>
              ) : (
                <>Window: Loading...</>
              )}
            </div>
            {signalsLastCalculated && !refreshingSignals && (
              <div className="text-xs text-gray-500">
                Signals calculated: {signalsLastCalculated.toLocaleString(undefined, {
                  year: 'numeric',
                  month: '2-digit',
                  day: '2-digit',
                  hour: '2-digit',
                  minute: '2-digit',
                  second: '2-digit',
                  hour12: true,
                  timeZoneName: 'short'
                })}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => fetchData(false)}
              disabled={isFetching}
              className="px-3 py-1.5 text-xs bg-gray-100 text-gray-700 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1"
              title="Refresh data"
            >
              {isFetching ? (
                <>
                  <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-gray-600"></div>
                  <span>Refreshing...</span>
                </>
              ) : (
                <>
                  <span>↻</span>
                  <span>Refresh</span>
                </>
              )}
            </button>
            <button
              onClick={handleRefreshSignals}
              disabled={refreshingSignals || loading}
              className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              title="Force recalculation of signals"
            >
              {refreshingSignals ? (
                <>
                  <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-white"></div>
                  <span>Refreshing...</span>
                </>
              ) : (
                <>
                  <span>🔄</span>
                  <span>Refresh Signals</span>
                </>
              )}
            </button>
          </div>
        </div>
        {alertRows.length === 0 ? (
          <div className="p-8 text-center text-gray-500">
            No active alerts
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Message</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Timestamp</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {alertRows}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Active Signals Table (Current State) */}
      {/* NOTE: Active Signals = current BUY/SELL state from watchlist, NOT emitted events.
          For events (Telegram messages, throttle records), see "Active Alerts" above. */}
      <div className="bg-white rounded-lg shadow border border-gray-200 mb-6">
        <div className="p-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold">Active Signals (Current State)</h3>
            <p className="text-xs text-gray-500">Current BUY/SELL signals from watchlist (not events)</p>
          </div>
        </div>
        {!monitoringData.active_signals || monitoringData.active_signals.length === 0 ? (
          <div className="p-8 text-center text-gray-500">
            No active signals
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Decision</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Strategy</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last Price</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Timestamp</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {monitoringData.active_signals.map((signal, idx) => {
                  // Robust null handling - never crash on missing data
                  const symbol = signal?.symbol || 'UNKNOWN';
                  const decision = signal?.decision || 'UNKNOWN';
                  const strategyKey = signal?.strategy_key ?? null;
                  const lastPrice = signal?.last_price ?? null;
                  const timestamp = signal?.timestamp || null;
                  
                  // Format timestamp safely
                  let formattedTimestamp = '—';
                  if (timestamp) {
                    try {
                      const date = new Date(timestamp);
                      if (!isNaN(date.getTime())) {
                        formattedTimestamp = date.toLocaleString();
                      }
                    } catch (e) {
                      // Invalid timestamp - show fallback
                      formattedTimestamp = '—';
                    }
                  }
                  
                  // Determine badge color based on decision
                  const badgeClass = decision === 'BUY' 
                    ? 'bg-green-100 text-green-800 border border-green-200'
                    : decision === 'SELL'
                    ? 'bg-red-100 text-red-800 border border-red-200'
                    : 'bg-gray-100 text-gray-800 border border-gray-200';
                  
                  return (
                    <tr key={`${symbol}-${idx}`} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">{symbol}</td>
                      <td className="px-4 py-3 text-sm">
                        <span className={`px-2 py-1 rounded text-xs font-semibold ${badgeClass}`}>
                          {decision}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">{strategyKey || 'N/A'}</td>
                      <td className="px-4 py-3 text-sm text-gray-900">
                        {lastPrice !== null && lastPrice > 0 ? `$${lastPrice.toFixed(4)}` : 'N/A'}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-500">{formattedTimestamp}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Signal Throttle Panel */}
      <div className="bg-white rounded-lg shadow border border-gray-200 mb-6">
        <div className="p-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold">Throttle (Mensajes Enviados)</h3>
            <p className="text-xs text-gray-500">Mensajes throttled que fueron enviados a Telegram</p>
          </div>
          <button
            onClick={fetchThrottle}
            className="px-3 py-1 text-sm bg-gray-100 text-gray-700 rounded hover:bg-gray-200"
            disabled={throttleLoading}
          >
            {throttleLoading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
        {throttleError && (
          <div className="px-4 py-2 text-sm text-red-600 bg-red-50 border-b border-red-100">
            {throttleError}
          </div>
        )}
        {throttleLoading && throttleEntries.length === 0 ? (
          <div className="p-6 text-center text-gray-500">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600 mx-auto mb-2"></div>
            Loading throttle data...
          </div>
        ) : throttleRows.length === 0 ? (
          <div className="p-6 text-center text-gray-500">
            No throttle activity recorded yet.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Strategy</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Side</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last Price</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Price Change %</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Reason</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last Event</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Ago</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {throttleRows}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Monitoring Workflows Box */}
      <div className="bg-white rounded-lg shadow border border-gray-200 mb-6">
        <div className="p-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold">Monitoring Workflows</h3>
            <p className="text-xs text-gray-500">
              Automated monitoring workflows with manual triggers
              {workflowsLastUpdate && (
                <span className="ml-2 text-gray-400">
                  • Updated {formatRelativeTime(Math.floor((Date.now() - workflowsLastUpdate.getTime()) / 1000))}
                </span>
              )}
              {workflowsRefreshing && (
                <span className="ml-2 text-blue-500">⟳ Refreshing...</span>
              )}
            </p>
          </div>
        </div>
        {/* Non-destructive error banner - doesn't clear the UI */}
        {workflowsError && (
          <div className="px-4 py-2 text-sm text-red-600 bg-red-50 border-b border-red-100">
            Error refreshing workflows: {workflowsError}
            <button
              onClick={() => {
                setWorkflowsError(null);
                fetchWorkflows(false);
              }}
              className="ml-2 text-red-700 underline hover:text-red-900"
            >
              Retry
            </button>
          </div>
        )}
        {/* Only show loading spinner on initial load when we have no data */}
        {workflowsLoading && workflows.length === 0 ? (
          <div className="p-6 text-center text-gray-500">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600 mx-auto mb-2"></div>
            Loading workflows...
          </div>
        ) : workflowRows.length === 0 ? (
          <div className="p-6 text-center text-gray-500">
            No workflows found
          </div>
        ) : (
          /* Keep the table mounted at all times - never disappears during refresh */
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="w-full">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Schedule</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last Run</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Messages</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {workflowRows}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Telegram Messages Dropdown */}
      <div className="bg-white rounded-lg shadow border border-gray-200">
        <div className="p-4 border-b border-gray-200">
          <button
            onClick={() => {
              const nextState = !showTelegramMessages;
              setShowTelegramMessages(nextState);
              if (nextState && safeTelegramMessages.length === 0) {
                onRequestTelegramRefresh?.();
              }
            }}
            className="flex items-center justify-between w-full text-left"
          >
            <h3 className="text-lg font-semibold">
              Telegram (Mensajes Bloqueados) ({safeTelegramMessages.length})
              {safeCoinFilter.trim() && (
                <span className="ml-2 text-sm font-normal text-gray-500">
                  (showing {filteredTelegramMessages.length})
                </span>
              )}
            </h3>
            <span className={`transform transition-transform ${showTelegramMessages ? 'rotate-180' : ''}`}>
              ▼
            </span>
          </button>
        </div>
        {showTelegramMessages && (
          <div>
            <div className="p-4 border-b border-gray-200">
              <input
                type="text"
                placeholder="Filter by coin/symbol (e.g., BTC, ALGO)"
                value={safeCoinFilter}
                onChange={(e) => setCoinFilter(e.target.value || '')}
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div className="max-h-96 overflow-y-auto">
              {telegramMessagesLoading ? (
                <div className="p-8 text-center">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-4"></div>
                  <p className="text-gray-500">Loading Telegram messages...</p>
                </div>
              ) : telegramItems.length === 0 ? (
                <div className="p-8 text-center text-gray-500">
                  {safeCoinFilter.trim() ? `No blocked messages found for "${safeCoinFilter}"` : 'No blocked messages yet'}
                </div>
              ) : (
                <div className="divide-y divide-gray-200">
                  {telegramItems}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

