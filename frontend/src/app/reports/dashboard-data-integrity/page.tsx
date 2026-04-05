'use client';

import React, { useState, useEffect } from 'react';
import { getApiUrl } from '@/lib/environment';

interface Inconsistency {
  id: string;
  severity: 'blocker' | 'high' | 'medium' | 'low';
  entity: 'watchlist' | 'trade' | 'portfolio' | 'alerts';
  symbol: string;
  field: string;
  dashboard_value: unknown;
  backend_value: unknown;
  source: {
    api: string;
    backend_module: string;
    db: string;
  };
  notes: string;
}

interface Report {
  run: {
    workflow: string;
    run_id: string;
    created_at: string;
    commit: string;
    branch: string;
    status: 'PASS' | 'FAIL';
  };
  summary: {
    inconsistencies_total: number;
    blockers: number;
    high: number;
    medium: number;
    low: number;
  };
  inconsistencies: Inconsistency[];
  cursor_prompt: string;
}

export default function DashboardDataIntegrityReportPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const fetchReport = async () => {
      try {
        setLoading(true);
        setError(null);
        const apiUrl = getApiUrl();
        const response = await fetch(`${apiUrl}/reports/dashboard-data-integrity/latest`);
        
        if (!response.ok) {
          if (response.status === 404) {
            setError('No report available yet. The workflow may not have run or completed.');
            return;
          }
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        if (data.status === 'not_found') {
          setError(data.message || 'No report available yet. The workflow may not have run or completed.');
          return;
        }
        
        if (data.status === 'success' && data.report) {
          setReport(data.report);
        } else {
          setError('Invalid report format received from server.');
        }
      } catch (err) {
        const errorMsg = err instanceof Error ? err.message : 'Unknown error';
        setError(errorMsg);
        console.error('Failed to fetch report:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchReport();
  }, []);

  const copyPromptToClipboard = () => {
    if (!report?.cursor_prompt) return;
    
    navigator.clipboard.writeText(report.cursor_prompt).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }).catch(err => {
      console.error('Failed to copy:', err);
      alert('Failed to copy to clipboard. Please select and copy manually.');
    });
  };

  const getSeverityColor = (severity: string): string => {
    switch (severity) {
      case 'blocker':
        return 'bg-red-100 text-red-800 border-red-300';
      case 'high':
        return 'bg-orange-100 text-orange-800 border-orange-300';
      case 'medium':
        return 'bg-yellow-100 text-yellow-800 border-yellow-300';
      case 'low':
        return 'bg-blue-100 text-blue-800 border-blue-300';
      default:
        return 'bg-gray-100 text-gray-800 border-gray-300';
    }
  };

  const formatValue = (value: unknown): string => {
    if (value === null || value === undefined) return 'null';
    if (typeof value === 'boolean') return value ? 'true' : 'false';
    if (typeof value === 'object') return JSON.stringify(value, null, 2);
    return String(value);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 py-8">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
            <p className="text-gray-500">Loading report...</p>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 py-8">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="bg-white rounded-lg shadow p-6">
            <h1 className="text-2xl font-bold text-gray-900 mb-4">Dashboard Data Integrity Report</h1>
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
              <p className="text-yellow-800">{error}</p>
            </div>
            <div className="mt-4">
              <a
                href="/"
                className="text-blue-600 hover:text-blue-800 underline"
              >
                ← Back to Dashboard
              </a>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!report) {
    return null;
  }

  return (
    <div className="min-h-screen bg-gray-50 py-8">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Dashboard Data Integrity Report</h1>
            <p className="text-sm text-gray-500 mt-1">Validates UI vs backend data integrity</p>
          </div>
          <a
            href="/"
            className="text-blue-600 hover:text-blue-800 underline text-sm"
          >
            ← Back to Dashboard
          </a>
        </div>

        {/* Run Metadata */}
        <div className="bg-white rounded-lg shadow mb-6 p-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4">Run Metadata</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <span className="text-sm text-gray-500">Workflow:</span>
              <p className="font-medium">{report.run.workflow}</p>
            </div>
            <div>
              <span className="text-sm text-gray-500">Status:</span>
              <span className={`ml-2 px-3 py-1 rounded-full text-sm font-semibold ${
                report.run.status === 'PASS' 
                  ? 'bg-green-100 text-green-800 border border-green-300' 
                  : 'bg-red-100 text-red-800 border border-red-300'
              }`}>
                {report.run.status}
              </span>
            </div>
            <div>
              <span className="text-sm text-gray-500">Run Date/Time:</span>
              <p className="font-medium">
                {new Date(report.run.created_at).toLocaleString()}
              </p>
            </div>
            <div>
              <span className="text-sm text-gray-500">Commit:</span>
              <p className="font-mono text-sm">{report.run.commit.substring(0, 8)}</p>
            </div>
            <div>
              <span className="text-sm text-gray-500">Branch:</span>
              <p className="font-medium">{report.run.branch}</p>
            </div>
            <div>
              <span className="text-sm text-gray-500">Run ID:</span>
              <p className="font-mono text-sm">{report.run.run_id}</p>
            </div>
          </div>
        </div>

        {/* Summary */}
        <div className="bg-white rounded-lg shadow mb-6 p-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4">Summary</h2>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div className="text-center">
              <div className="text-3xl font-bold text-gray-900">{report.summary.inconsistencies_total}</div>
              <div className="text-sm text-gray-500">Total</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-bold text-red-600">{report.summary.blockers}</div>
              <div className="text-sm text-gray-500">Blockers</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-bold text-orange-600">{report.summary.high}</div>
              <div className="text-sm text-gray-500">High</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-bold text-yellow-600">{report.summary.medium}</div>
              <div className="text-sm text-gray-500">Medium</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-bold text-blue-600">{report.summary.low}</div>
              <div className="text-sm text-gray-500">Low</div>
            </div>
          </div>
        </div>

        {/* Inconsistencies Table */}
        {report.inconsistencies.length > 0 ? (
          <div className="bg-white rounded-lg shadow mb-6">
            <div className="p-6 border-b border-gray-200">
              <h2 className="text-xl font-semibold text-gray-900">Findings</h2>
              <p className="text-sm text-gray-500 mt-1">
                {report.inconsistencies.length} inconsistency(ies) found
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Severity</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Entity</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Field</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Dashboard Value</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Backend Value</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {report.inconsistencies.map((inc) => (
                    <tr key={inc.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm font-mono">{inc.id}</td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-1 text-xs font-semibold rounded-full border ${getSeverityColor(inc.severity)}`}>
                          {inc.severity}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm">{inc.entity}</td>
                      <td className="px-4 py-3 text-sm font-medium">{inc.symbol}</td>
                      <td className="px-4 py-3 text-sm font-mono">{inc.field}</td>
                      <td className="px-4 py-3 text-sm">
                        <code className="bg-gray-100 px-2 py-1 rounded text-xs">
                          {formatValue(inc.dashboard_value)}
                        </code>
                      </td>
                      <td className="px-4 py-3 text-sm">
                        <code className="bg-gray-100 px-2 py-1 rounded text-xs">
                          {formatValue(inc.backend_value)}
                        </code>
                      </td>
                      <td className="px-4 py-3 text-sm">
                        <div className="text-xs">
                          <div>API: {inc.source.api.split('?')[0]}</div>
                          <div className="text-gray-500">DB: {inc.source.db}</div>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="bg-green-50 border border-green-200 rounded-lg p-6 mb-6">
            <p className="text-green-800 font-medium">✅ No inconsistencies found. Dashboard data integrity is valid.</p>
          </div>
        )}

        {/* Cursor Prompt */}
        <div className="bg-white rounded-lg shadow mb-6">
          <div className="p-6 border-b border-gray-200 flex items-center justify-between">
            <div>
              <h2 className="text-xl font-semibold text-gray-900">Cursor Prompt</h2>
              <p className="text-sm text-gray-500 mt-1">Ready-to-copy prompt for fixing inconsistencies</p>
            </div>
            <button
              onClick={copyPromptToClipboard}
              className={`px-4 py-2 text-white rounded text-sm font-medium transition-colors ${
                copied 
                  ? 'bg-green-600 hover:bg-green-700' 
                  : 'bg-blue-600 hover:bg-blue-700'
              }`}
            >
              {copied ? '✓ Copied!' : 'Copy Prompt'}
            </button>
          </div>
          <div className="p-6">
            <pre className="bg-gray-50 border border-gray-200 rounded p-4 overflow-x-auto text-sm font-mono">
              {report.cursor_prompt}
            </pre>
          </div>
        </div>

        {/* Re-run Check */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4">Re-run Check</h2>
          <p className="text-sm text-gray-600 mb-4">
            To re-run the Dashboard Data Integrity workflow, push changes to the frontend or trigger it manually from GitHub Actions.
          </p>
          <div className="flex gap-4">
            <a
              href="https://github.com/ccruz0/crypto-2.0/actions/workflows/dashboard-data-integrity.yml"
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2 bg-gray-100 text-gray-700 rounded hover:bg-gray-200 text-sm font-medium"
            >
              View in GitHub Actions
            </a>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm font-medium"
            >
              Refresh Report
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

