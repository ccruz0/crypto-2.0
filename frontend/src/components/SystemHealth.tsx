'use client';

import React, { useState, useEffect, useRef } from 'react';
import { getSystemHealth, SystemHealth, testTelegram } from '@/lib/api';

interface SystemHealthProps {
  className?: string;
}

export default function SystemHealthPanel({ className = '' }: SystemHealthProps) {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adminKey, setAdminKey] = useState<string>('');
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [testCooldown, setTestCooldown] = useState<number>(0);
  const [isTesting, setIsTesting] = useState(false);
  const cooldownIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const fetchHealth = async () => {
    try {
      setError(null);
      const data = await getSystemHealth();
      setHealth(data);
    } catch (err) {
      // Silently handle errors - don't crash the app
      setError(err instanceof Error ? err.message : 'Failed to fetch system health');
      console.error('Error fetching system health:', err);
      // Set health to null to show error state instead of crashing
      setHealth(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHealth();
    // Poll every 60 seconds
    const interval = setInterval(fetchHealth, 60000);
    return () => clearInterval(interval);
  }, []);

  // Cooldown countdown
  useEffect(() => {
    if (testCooldown > 0) {
      cooldownIntervalRef.current = setInterval(() => {
        setTestCooldown((prev) => {
          if (prev <= 1) {
            if (cooldownIntervalRef.current) {
              clearInterval(cooldownIntervalRef.current);
            }
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    } else {
      if (cooldownIntervalRef.current) {
        clearInterval(cooldownIntervalRef.current);
      }
    }
    return () => {
      if (cooldownIntervalRef.current) {
        clearInterval(cooldownIntervalRef.current);
      }
    };
  }, [testCooldown]);

  const handleTestTelegram = async () => {
    if (!adminKey.trim()) {
      setTestResult({ success: false, message: 'Please enter admin key' });
      return;
    }

    if (testCooldown > 0) {
      setTestResult({ success: false, message: `Rate limited. Wait ${testCooldown}s` });
      return;
    }

    setIsTesting(true);
    setTestResult(null);

    try {
      const result = await testTelegram(adminKey);
      if (result.ok) {
        setTestResult({ success: true, message: 'Test sent successfully' });
        setTestCooldown(60); // Start 60s cooldown
      } else {
        setTestResult({ success: false, message: result.error || 'Failed to send test' });
        if (result.error === 'rate_limited') {
          setTestCooldown(60);
        }
      }
    } catch (err) {
      setTestResult({ success: false, message: err instanceof Error ? err.message : 'Unknown error' });
    } finally {
      setIsTesting(false);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'PASS':
        return 'bg-green-500';
      case 'WARN':
        return 'bg-yellow-500';
      case 'FAIL':
        return 'bg-red-500';
      default:
        return 'bg-gray-500';
    }
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case 'PASS':
        return 'PASS';
      case 'WARN':
        return 'WARN';
      case 'FAIL':
        return 'FAIL';
      default:
        return 'UNKNOWN';
    }
  };

  if (loading && !health) {
    return (
      <div className={`bg-white rounded-lg shadow p-4 ${className}`}>
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold">System Health</h3>
          <div className="text-sm text-gray-500">Loading...</div>
        </div>
      </div>
    );
  }

  if (error && !health) {
    return (
      <div className={`bg-white rounded-lg shadow p-4 ${className}`}>
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold">System Health</h3>
          <div className="text-sm text-red-500">Error: {error}</div>
        </div>
      </div>
    );
  }

  if (!health) return null;

  const { global_status, timestamp, market_data, market_updater, signal_monitor, telegram, trade_system } = health;

  return (
    <div className={`bg-white rounded-lg shadow p-4 ${className}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-semibold">System Health</h3>
          <div className={`w-3 h-3 rounded-full ${getStatusColor(global_status)}`} title={global_status} />
          <span className="text-sm font-medium">{getStatusText(global_status)}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-sm text-blue-600 hover:text-blue-800"
          >
            {expanded ? 'Hide' : 'Details'}
          </button>
          <span className="text-xs text-gray-500">
            {timestamp ? new Date(timestamp).toLocaleTimeString() : ''}
          </span>
        </div>
      </div>

      {/* Status lights */}
      <div className="grid grid-cols-5 gap-2 mb-3">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${getStatusColor(market_data.status)}`} />
          <span className="text-xs">Market</span>
        </div>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${getStatusColor(market_updater.status)}`} />
          <span className="text-xs">Updater</span>
        </div>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${getStatusColor(signal_monitor.status)}`} />
          <span className="text-xs">Monitor</span>
        </div>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${getStatusColor(telegram.status)}`} />
          <span className="text-xs">Telegram</span>
        </div>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${getStatusColor(trade_system.status)}`} />
          <span className="text-xs">Trade</span>
        </div>
      </div>

      {/* Expandable details */}
      {expanded && (
        <div className="mt-3 pt-3 border-t space-y-2 text-sm">
          <div>
            <strong>Market Data:</strong> {market_data.fresh_symbols} fresh, {market_data.stale_symbols} stale
            {market_data.max_age_minutes !== null && (
              <span className="text-gray-600"> (max age: {market_data.max_age_minutes.toFixed(1)} min)</span>
            )}
          </div>
          <div>
            <strong>Market Updater:</strong> {market_updater.is_running ? 'RUNNING' : 'DOWN'}
            {market_updater.last_heartbeat_age_minutes !== null && (
              <span className="text-gray-600"> (last heartbeat: {market_updater.last_heartbeat_age_minutes.toFixed(1)} min ago)</span>
            )}
          </div>
          <div>
            <strong>Signal Monitor:</strong> {signal_monitor.is_running ? 'Running' : 'Stopped'}
            {signal_monitor.last_cycle_age_minutes !== null && (
              <span className="text-gray-600"> (last cycle: {signal_monitor.last_cycle_age_minutes.toFixed(1)} min ago)</span>
            )}
          </div>
          <div>
            <strong>Telegram:</strong> {telegram.enabled ? 'Enabled' : 'Disabled'}
            {telegram.last_send_ok !== null && (
              <span className="text-gray-600"> (last send: {telegram.last_send_ok ? 'OK' : 'Failed'})</span>
            )}
          </div>
          <div>
            <strong>Trade System:</strong> {trade_system.open_orders} open orders
            {trade_system.max_open_orders !== null && (
              <span className="text-gray-600"> (max: {trade_system.max_open_orders})</span>
            )}
          </div>

          {/* Admin Test Telegram Section */}
          <div className="mt-4 pt-3 border-t">
            <div className="flex items-center gap-2 mb-2">
              <label htmlFor="admin-key" className="text-sm font-medium">
                Admin Key:
              </label>
              <input
                id="admin-key"
                type="password"
                value={adminKey}
                onChange={(e) => setAdminKey(e.target.value)}
                placeholder="Enter admin key"
                className="flex-1 px-2 py-1 text-xs border border-gray-300 rounded"
              />
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={handleTestTelegram}
                disabled={isTesting || testCooldown > 0 || !adminKey.trim()}
                className={`px-3 py-1 text-xs rounded ${
                  isTesting || testCooldown > 0 || !adminKey.trim()
                    ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                    : 'bg-blue-600 text-white hover:bg-blue-700'
                }`}
              >
                {isTesting
                  ? 'Sending...'
                  : testCooldown > 0
                  ? `Wait ${testCooldown}s`
                  : 'Send Test Telegram'}
              </button>
              {testResult && (
                <span className={`text-xs ${testResult.success ? 'text-green-600' : 'text-red-600'}`}>
                  {testResult.message}
                </span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

