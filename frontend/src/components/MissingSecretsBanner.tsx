'use client';

import React, { useState, useCallback, useMemo, useEffect } from 'react';
import {
  getSecretsStatus,
  getRecoveryStatus,
  submitSecretIntake,
  applyBackendRecovery,
  type SecretsStatusResponse,
  type SecretCatalogItem,
  type RecoveryStatusPayload,
} from '@/lib/api';
import { getApiUrl } from '@/lib/environment';
import RotateAdminKeyModal from '@/components/RotateAdminKeyModal';

const GROUP_ORDER = ['trading', 'api', 'telegram', 'automation', 'github'];

const GROUP_LABEL: Record<string, string> = {
  trading: 'Trading (exchange)',
  api: 'API keys',
  telegram: 'Telegram',
  automation: 'Automation (Notion / OpenClaw)',
  github: 'GitHub',
};

function sortCatalog(rows: SecretCatalogItem[]): SecretCatalogItem[] {
  const rank = (g: string) => {
    const i = GROUP_ORDER.indexOf(g);
    return i === -1 ? 99 : i;
  };
  return [...rows].sort((a, b) => {
    const rg = rank(a.group) - rank(b.group);
    if (rg !== 0) return rg;
    return a.label.localeCompare(b.label);
  });
}

/**
 * Simple admin view: list configured keys (masked), replace into runtime.env via secrets-intake.
 */
export default function MissingSecretsBanner() {
  const [adminKey, setAdminKey] = useState('');
  const [status, setStatus] = useState<SecretsStatusResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [replaceRow, setReplaceRow] = useState<SecretCatalogItem | null>(null);
  const [pasteValue, setPasteValue] = useState('');
  const [persistSsm, setPersistSsm] = useState(false);
  const [replaceSaving, setReplaceSaving] = useState(false);
  const [replaceErr, setReplaceErr] = useState<string | null>(null);
  const [showRotateAdminModal, setShowRotateAdminModal] = useState(false);
  const [recoveryInfo, setRecoveryInfo] = useState<RecoveryStatusPayload | null>(null);
  const [applyMsg, setApplyMsg] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [healthPollMsg, setHealthPollMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!toastMessage) return;
    const id = window.setTimeout(() => setToastMessage(null), 4000);
    return () => window.clearTimeout(id);
  }, [toastMessage]);

  const loadStatus = useCallback(
    async (keyOverride?: string) => {
      const effectiveKey = (keyOverride ?? adminKey).trim();
      setLoadError(null);
      setLoading(true);
      try {
        const [data, rec] = await Promise.all([
          getSecretsStatus(effectiveKey),
          getRecoveryStatus(effectiveKey).catch(() => null),
        ]);
        setStatus(data);
        setRecoveryInfo(rec);
      } catch (e) {
        setStatus(null);
        setRecoveryInfo(null);
        setLoadError(e instanceof Error ? e.message : 'Failed to load');
      } finally {
        setLoading(false);
      }
    },
    [adminKey],
  );

  const catalogRows = useMemo(() => {
    const raw = status?.secrets_catalog;
    if (!raw?.length) return [];
    return sortCatalog(raw);
  }, [status?.secrets_catalog]);

  const openReplace = (row: SecretCatalogItem) => {
    setReplaceRow(row);
    setPasteValue('');
    setReplaceErr(null);
    setPersistSsm(row.env_var === 'GITHUB_APP_CLIENT_ID');
  };

  const saveReplace = async () => {
    if (!replaceRow || !adminKey.trim()) return;
    const v = pasteValue.trim();
    if (!v) {
      setReplaceErr('Paste a value first.');
      return;
    }
    setReplaceSaving(true);
    setReplaceErr(null);
    try {
      await submitSecretIntake(adminKey, replaceRow.env_var, v, persistSsm);
      setToastMessage(`${replaceRow.env_var} saved to runtime.env`);
      setReplaceRow(null);
      await loadStatus();
    } catch (e) {
      setReplaceErr(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setReplaceSaving(false);
    }
  };

  const runApplyRecovery = async () => {
    if (!adminKey.trim()) {
      setApplyMsg('Admin key required.');
      return;
    }
    if (!recoveryInfo?.recovery_runnable) return;
    setApplying(true);
    setApplyMsg(null);
    setHealthPollMsg(null);
    try {
      const res = await applyBackendRecovery(adminKey);
      setApplyMsg(res.message);
      const base = getApiUrl();
      for (let i = 0; i < 40; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        try {
          const ping = await fetch(`${base}/ping_fast`, { cache: 'no-store' });
          if (ping.ok) {
            setHealthPollMsg('Backend is up again. Reloading list…');
            await loadStatus();
            return;
          }
        } catch {
          /* still down */
        }
      }
      setHealthPollMsg('Still waiting — check the server manually.');
    } catch (e) {
      setApplyMsg(e instanceof Error ? e.message : 'Apply failed');
    } finally {
      setApplying(false);
    }
  };

  const clientIdHint = status?.context?.github_app_client_id_status;
  const automation = status?.automation_readiness;
  const blockingMissing = status?.missing?.length ?? 0;

  return (
    <div className="relative mb-4 rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900/50">
      {toastMessage && (
        <div
          role="status"
          className="fixed bottom-4 right-4 z-[110] rounded-md bg-green-800 px-4 py-2 text-xs font-medium text-white shadow-lg dark:bg-green-900"
        >
          {toastMessage}
        </div>
      )}
      <RotateAdminKeyModal
        isOpen={showRotateAdminModal}
        onClose={() => setShowRotateAdminModal(false)}
        currentAdminKey={adminKey}
        onRotated={async (newKey) => {
          setAdminKey(newKey);
          setToastMessage('Admin key updated — save it somewhere safe.');
          await loadStatus(newKey);
        }}
      />

      {replaceRow && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4"
          role="dialog"
          aria-modal="true"
        >
          <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-4 shadow-xl dark:border-gray-600 dark:bg-slate-900">
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Replace: {replaceRow.label}</h2>
            <p className="mt-1 font-mono text-xs text-gray-500 dark:text-gray-400">{replaceRow.env_var}</p>
            <p className="mt-2 text-xs text-gray-600 dark:text-gray-400">
              Paste the new value. It is written to <span className="font-medium">secrets/runtime.env</span> on the
              server (and the running process picks it up for most keys). Nothing is stored in the browser after save.
            </p>
            <textarea
              value={pasteValue}
              onChange={(e) => setPasteValue(e.target.value)}
              rows={4}
              autoComplete="off"
              className="mt-3 w-full rounded border border-gray-300 p-2 font-mono text-xs dark:border-gray-600 dark:bg-slate-800"
              placeholder="New value…"
            />
            {replaceRow.env_var === 'GITHUB_APP_CLIENT_ID' && (
              <label className="mt-2 flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
                <input type="checkbox" checked={persistSsm} onChange={(e) => setPersistSsm(e.target.checked)} />
                Also try AWS SSM (if configured on this host)
              </label>
            )}
            {replaceErr && <p className="mt-2 text-xs text-red-600">{replaceErr}</p>}
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                disabled={replaceSaving}
                onClick={() => saveReplace()}
                className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {replaceSaving ? 'Saving…' : 'Save'}
              </button>
              <button
                type="button"
                onClick={() => setReplaceRow(null)}
                className="rounded border border-gray-300 px-3 py-1.5 text-xs dark:border-gray-600"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Keys &amp; secrets</h2>
        <p className="text-xs text-slate-600 dark:text-slate-400">
          Load once with your admin key. Values show as hidden except the last three characters. Use Replace to update{' '}
          <span className="font-medium">runtime.env</span>.
        </p>
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="text-xs font-medium text-slate-700 dark:text-slate-300">
          Admin key
          <input
            type="password"
            autoComplete="off"
            value={adminKey}
            onChange={(e) => setAdminKey(e.target.value)}
            className="ml-2 rounded border border-slate-300 px-2 py-1 text-xs dark:border-slate-600 dark:bg-slate-800"
            placeholder="X-Admin-Key"
          />
        </label>
        <button
          type="button"
          disabled={loading}
          onClick={() => loadStatus()}
          className="rounded bg-slate-800 px-3 py-1 text-xs text-white hover:bg-slate-700 disabled:opacity-50 dark:bg-slate-700"
        >
          {loading ? 'Loading…' : 'Load'}
        </button>
        <button
          type="button"
          disabled={!adminKey.trim()}
          onClick={() => setShowRotateAdminModal(true)}
          className="rounded border border-slate-400 bg-white px-3 py-1 text-xs font-medium text-slate-800 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-500 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700"
        >
          Change admin key…
        </button>
      </div>

      {loadError && <p className="mt-2 text-xs text-red-600">{loadError}</p>}

      {status && (
        <>
          {status.overall === 'action_required' && blockingMissing > 0 && (
            <p className="mt-2 text-xs font-medium text-amber-800 dark:text-amber-200">
              Some items are still required for the current mode ({blockingMissing}).
            </p>
          )}
          {clientIdHint === 'missing' && (
            <p className="mt-1 text-xs text-amber-800 dark:text-amber-200">
              GitHub App Client ID is missing — add it below (GitHub → App → Client ID).
            </p>
          )}
          {automation?.applicable && (automation.missing?.length ?? 0) > 0 && (
            <p className="mt-1 text-xs text-sky-800 dark:text-sky-200">
              Before turning off trading-only: {automation.missing?.length} automation secret(s) still empty.
            </p>
          )}
        </>
      )}

      {catalogRows.length > 0 && (
        <div className="mt-4 overflow-x-auto rounded border border-slate-200 bg-white dark:border-slate-600 dark:bg-slate-950">
          <table className="w-full min-w-[520px] border-collapse text-left text-xs">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-100 dark:border-slate-600 dark:bg-slate-800">
                <th className="px-3 py-2 font-medium text-slate-700 dark:text-slate-200">Setting</th>
                <th className="px-3 py-2 font-medium text-slate-700 dark:text-slate-200">Variable</th>
                <th className="px-3 py-2 font-medium text-slate-700 dark:text-slate-200">Stored value</th>
                <th className="px-3 py-2 font-medium text-slate-700 dark:text-slate-200"> </th>
              </tr>
            </thead>
            <tbody>
              {catalogRows.map((row) => (
                <tr key={row.env_var} className="border-b border-slate-100 dark:border-slate-800">
                  <td className="px-3 py-2 text-slate-800 dark:text-slate-100">
                    <div className="font-medium">{row.label}</div>
                    <div className="text-[10px] uppercase tracking-wide text-slate-500 dark:text-slate-400">
                      {GROUP_LABEL[row.group] || row.group}
                    </div>
                  </td>
                  <td className="px-3 py-2 font-mono text-[11px] text-slate-600 dark:text-slate-300">{row.env_var}</td>
                  <td className="px-3 py-2 font-mono text-[11px] text-slate-700 dark:text-slate-200">{row.masked}</td>
                  <td className="px-3 py-2">
                    {row.intake_allowed ? (
                      <button
                        type="button"
                        disabled={!adminKey.trim()}
                        onClick={() => openReplace(row)}
                        className="rounded border border-blue-600 px-2 py-1 text-[11px] font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-40 dark:border-blue-500 dark:text-blue-300 dark:hover:bg-slate-800"
                      >
                        Replace…
                      </button>
                    ) : (
                      <span className="text-[10px] text-slate-400">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {status && !catalogRows.length && (
        <p className="mt-3 text-xs text-slate-600 dark:text-slate-400">
          This server build does not expose the full secrets list yet. Update the backend and reload.
        </p>
      )}

      <details className="mt-4 rounded border border-slate-200 bg-white p-3 text-xs dark:border-slate-600 dark:bg-slate-950">
        <summary className="cursor-pointer font-medium text-slate-700 dark:text-slate-200">
          Advanced: recovery restart
        </summary>
        {recoveryInfo && (
          <div className="mt-2 space-y-2 text-slate-600 dark:text-slate-400">
            <p>
              Auto-restart: {String(recoveryInfo.auto_restart_enabled)} · compose:{' '}
              {String(recoveryInfo.compose_project_configured)} · runnable: {String(recoveryInfo.recovery_runnable)}
            </p>
            {recoveryInfo.recovery_runnable && (
              <button
                type="button"
                disabled={applying || !adminKey.trim()}
                onClick={runApplyRecovery}
                className="rounded bg-amber-700 px-2 py-1 text-xs text-white hover:bg-amber-800 disabled:opacity-50"
              >
                {applying ? 'Applying…' : 'Apply & recreate backend-aws'}
              </button>
            )}
            {applyMsg && <p className="text-slate-700 dark:text-slate-300">{applyMsg}</p>}
            {healthPollMsg && <p className="text-green-700 dark:text-green-400">{healthPollMsg}</p>}
          </div>
        )}
      </details>
    </div>
  );
}
