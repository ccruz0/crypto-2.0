'use client';

import React, { useState, useCallback, useMemo, useEffect } from 'react';
import { getApiUrl } from '@/lib/environment';
import {
  getSecretsStatus,
  getRecoveryStatus,
  submitSecretIntake,
  applyBackendRecovery,
  getSystemHealth,
  type SecretsStatusResponse,
  type SecretMissingItem,
  type RecoveryStatusPayload,
  type DeployGithubAuthSnapshot,
} from '@/lib/api';
import GithubAppClientIdModal from '@/components/GithubAppClientIdModal';
import RotateAdminKeyModal from '@/components/RotateAdminKeyModal';

function mergeMissingLists(a: SecretMissingItem[], b: SecretMissingItem[]): SecretMissingItem[] {
  const seen = new Set<string>();
  const out: SecretMissingItem[] = [];
  for (const m of [...a, ...b]) {
    if (!seen.has(m.env_var)) {
      seen.add(m.env_var);
      out.push(m);
    }
  }
  return out;
}

/**
 * Action-required UI when registered secrets are missing (automation / AWS GitHub App).
 * Admin key is kept in component state only; secret values are cleared after submit.
 */
export default function MissingSecretsBanner() {
  const [adminKey, setAdminKey] = useState('');
  const [status, setStatus] = useState<SecretsStatusResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const [selectedVar, setSelectedVar] = useState<string>('');
  const [secretValue, setSecretValue] = useState('');
  const [persistSsm, setPersistSsm] = useState(true);
  const [submitMsg, setSubmitMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [recoveryInfo, setRecoveryInfo] = useState<RecoveryStatusPayload | null>(null);
  const [applyMsg, setApplyMsg] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [healthPollMsg, setHealthPollMsg] = useState<string | null>(null);
  const [showClientIdModal, setShowClientIdModal] = useState(false);
  const [showRotateAdminModal, setShowRotateAdminModal] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [deployGithubAuth, setDeployGithubAuth] = useState<DeployGithubAuthSnapshot | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSystemHealth()
      .then((h) => {
        if (!cancelled && h.deploy_github_auth) setDeployGithubAuth(h.deploy_github_auth);
      })
      .catch(() => {
        if (!cancelled) setDeployGithubAuth(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!toastMessage) return;
    const id = window.setTimeout(() => setToastMessage(null), 4000);
    return () => window.clearTimeout(id);
  }, [toastMessage]);

  const loadStatus = useCallback(async (keyOverride?: string) => {
    const effectiveKey = (keyOverride ?? adminKey).trim();
    setLoadError(null);
    setLoading(true);
    try {
      const [data, rec, health] = await Promise.all([
        getSecretsStatus(effectiveKey),
        getRecoveryStatus(effectiveKey).catch(() => null),
        getSystemHealth().catch(() => null),
      ]);
      setStatus(data);
      setRecoveryInfo(rec);
      if (health?.deploy_github_auth) {
        setDeployGithubAuth(health.deploy_github_auth);
      }
      const readinessMissing =
        data.automation_readiness?.applicable === true ? (data.automation_readiness.missing ?? []) : [];
      const merged = mergeMissingLists(data.missing, readinessMissing);
      if (merged.length > 0) {
        setSelectedVar((prev) => (merged.some((m) => m.env_var === prev) ? prev : merged[0].env_var));
      }
    } catch (e) {
      setStatus(null);
      setRecoveryInfo(null);
      setLoadError(e instanceof Error ? e.message : 'Failed to load status');
    } finally {
      setLoading(false);
    }
  }, [adminKey]);

  const onSubmitOne = async () => {
    if (!adminKey.trim() || !selectedVar || !secretValue.trim()) {
      setSubmitMsg({ ok: false, text: 'Admin key, variable, and value are required.' });
      return;
    }
    setSubmitting(true);
    setSubmitMsg(null);
    try {
      const res = await submitSecretIntake(adminKey, selectedVar, secretValue.trim(), persistSsm);
      setSecretValue('');
      setSubmitMsg({
        ok: true,
        text: res.message || 'Saved.',
      });
      await loadStatus();
    } catch (e) {
      setSubmitMsg({
        ok: false,
        text: e instanceof Error ? e.message : 'Save failed',
      });
    } finally {
      setSubmitting(false);
    }
  };

  const missing: SecretMissingItem[] = status?.missing ?? [];
  const readiness = status?.automation_readiness;
  const readinessApplicable = readiness?.applicable === true;
  const readinessMissing: SecretMissingItem[] = readinessApplicable ? (readiness?.missing ?? []) : [];
  const readinessNote = readiness?.note;
  const combinedForIntake = useMemo(
    () => mergeMissingLists(missing, readinessMissing),
    [missing, readinessMissing],
  );
  const actionRequired = status?.overall === 'action_required';
  const canApplyRecovery = Boolean(recoveryInfo?.recovery_runnable);
  const clientIdStatus = status?.context?.github_app_client_id_status;
  const showAddGithubClientIdButton = clientIdStatus === 'missing';
  const clientIdReadinessLabel =
    clientIdStatus === 'missing'
      ? 'GitHub App Client ID missing'
      : clientIdStatus === 'present'
        ? 'GitHub App Client ID present'
        : null;

  const deployAuthMainLine =
    deployGithubAuth?.available &&
    deployGithubAuth.last_source &&
    (deployGithubAuth.last_source === 'github_app'
      ? 'Last deploy auth: GitHub App'
      : deployGithubAuth.last_source === 'github_token' || deployGithubAuth.last_source === 'legacy_pat'
        ? 'Last deploy auth: GitHub token'
        : null);

  const deployAuthErrorCompact = (() => {
    if (!deployGithubAuth?.available || !deployGithubAuth.last_error?.trim()) return null;
    const e = deployGithubAuth.last_error.trim();
    return e.length > 200 ? `${e.slice(0, 200)}…` : e;
  })();

  const runApplyRecovery = async () => {
    if (!adminKey.trim()) {
      setApplyMsg('Admin key required.');
      return;
    }
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
            setHealthPollMsg('Health check: backend responded OK. Reloading status…');
            await loadStatus();
            return;
          }
        } catch {
          /* still down */
        }
      }
      setHealthPollMsg('Health check: timeout — verify the container manually.');
    } catch (e) {
      setApplyMsg(e instanceof Error ? e.message : 'Apply recovery failed');
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="relative mb-4 rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-900/60 dark:bg-amber-950/40">
      {toastMessage && (
        <div
          role="status"
          className="fixed bottom-4 right-4 z-[110] rounded-md bg-green-800 px-4 py-2 text-xs font-medium text-white shadow-lg dark:bg-green-900"
        >
          {toastMessage}
        </div>
      )}
      <GithubAppClientIdModal
        isOpen={showClientIdModal}
        onClose={() => setShowClientIdModal(false)}
        adminKey={adminKey}
        persistSsm={persistSsm}
        onSaved={async () => {
          setToastMessage('Client ID saved');
          await loadStatus();
        }}
      />
      <RotateAdminKeyModal
        isOpen={showRotateAdminModal}
        onClose={() => setShowRotateAdminModal(false)}
        currentAdminKey={adminKey}
        onRotated={async (newKey) => {
          setAdminKey(newKey);
          setToastMessage('Admin key updated — copy it somewhere safe.');
          await loadStatus(newKey);
        }}
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-amber-900 dark:text-amber-100">
            Missing configuration (secrets)
          </h2>
          <p className="text-xs text-amber-800 dark:text-amber-200/90">
            Load status with an admin key to see variables required for the current mode and, when trading-only, what is
            still needed before automation. Values are sent once and not kept in the UI after submit.
          </p>
          {clientIdReadinessLabel && (
            <p
              className={`mt-1 text-xs ${
                clientIdStatus === 'present'
                  ? 'text-green-700 dark:text-green-400'
                  : 'text-amber-900 dark:text-amber-100/90'
              }`}
            >
              {clientIdReadinessLabel}
            </p>
          )}
          {deployAuthMainLine && (
            <p className="mt-1 text-xs text-gray-700 dark:text-gray-300">{deployAuthMainLine}</p>
          )}
          {!deployAuthMainLine && deployAuthErrorCompact && (
            <p className="mt-1 text-xs text-red-600 dark:text-red-400">{deployAuthErrorCompact}</p>
          )}
          {deployAuthMainLine && deployAuthErrorCompact && deployGithubAuth?.last_ok !== true && (
            <p className="mt-0.5 text-xs text-red-600 dark:text-red-400">{deployAuthErrorCompact}</p>
          )}
        </div>
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="rounded bg-amber-600 px-3 py-1 text-xs font-medium text-white hover:bg-amber-700"
        >
          {expanded ? 'Hide' : 'Open'}
        </button>
      </div>

      {expanded && (
        <div className="mt-3 space-y-3 border-t border-amber-200 pt-3 dark:border-amber-800">
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs font-medium text-gray-700 dark:text-gray-300">
              Admin key
              <input
                type="password"
                autoComplete="off"
                value={adminKey}
                onChange={(e) => setAdminKey(e.target.value)}
                className="ml-2 rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-slate-800"
                placeholder="X-Admin-Key"
              />
            </label>
            <button
              type="button"
              disabled={loading}
              onClick={() => loadStatus()}
              className="rounded bg-gray-800 px-3 py-1 text-xs text-white hover:bg-gray-700 disabled:opacity-50"
            >
              {loading ? 'Loading…' : 'Load status'}
            </button>
            <button
              type="button"
              disabled={!adminKey.trim()}
              onClick={() => setShowRotateAdminModal(true)}
              className="rounded border border-gray-600 bg-white px-3 py-1 text-xs font-medium text-gray-800 hover:bg-gray-100 disabled:opacity-50 dark:border-gray-500 dark:bg-slate-800 dark:text-gray-100 dark:hover:bg-slate-700"
              title="Requires the current admin key in the field above"
            >
              Change admin key…
            </button>
          </div>

          {loadError && <p className="text-xs text-red-600">{loadError}</p>}

          {status && (
            <div className="text-xs space-y-1">
              <p>
                <span className="font-medium">Mode:</span> ATP_TRADING_ONLY={String(status.context.atp_trading_only)}{' '}
                · ENV={status.context.environment} · AWS={String(status.context.aws)} · skipped requirements (not
                applicable): {status.skipped_count}
              </p>
              {status.context.github_legacy_pat_active && (
                <p className="text-green-700 dark:text-green-400">
                  Legacy GitHub PAT path active — GitHub App variables may be skipped.
                </p>
              )}
              {showAddGithubClientIdButton && (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <p className="text-xs text-amber-900 dark:text-amber-100/90">
                    GitHub App Client ID (recommended for JWT) is not set.
                  </p>
                  <button
                    type="button"
                    onClick={() => setShowClientIdModal(true)}
                    className="rounded bg-amber-800 px-2.5 py-1 text-xs font-medium text-white hover:bg-amber-900 dark:bg-amber-700 dark:hover:bg-amber-600"
                  >
                    Add GitHub App Client ID
                  </button>
                </div>
              )}
              {actionRequired ? (
                <p className="font-medium text-red-700 dark:text-red-400">
                  Required now: {missing.length} secret(s) missing for enabled features in the current mode.
                </p>
              ) : (
                <p className="font-medium text-green-700 dark:text-green-400">
                  Required for current mode: no registered secrets missing — trading-only health is not blocked by these
                  checks.
                </p>
              )}
            </div>
          )}

          {missing.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs font-medium text-gray-800 dark:text-gray-200">Required for current mode</p>
              <ul className="max-h-40 list-inside list-disc overflow-y-auto text-xs text-gray-800 dark:text-gray-200">
                {missing.map((m) => (
                  <li key={m.env_var}>
                    <span className="font-mono">{m.env_var}</span> — {m.blocked_service}: {m.why}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {readinessApplicable && readinessMissing.length > 0 && (
            <div className="rounded border border-sky-200 bg-sky-50 p-3 dark:border-sky-900/60 dark:bg-sky-950/30">
              <p className="text-xs font-semibold text-sky-900 dark:text-sky-100">
                Required to enable automation (not blocking current trading-only)
              </p>
              <p className="mt-1 text-xs font-medium text-sky-800 dark:text-sky-200">
                {readinessMissing.length} secret(s) still needed before you can set ATP_TRADING_ONLY=0.
              </p>
              {readinessNote && <p className="mt-1 text-xs text-sky-800/90 dark:text-sky-200/90">{readinessNote}</p>}
              <ul className="mt-2 max-h-40 list-inside list-disc overflow-y-auto text-xs text-sky-950 dark:text-sky-100">
                {readinessMissing.map((m) => (
                  <li key={`ar-${m.env_var}`}>
                    <span className="font-mono">{m.env_var}</span> — {m.blocked_service}: {m.why}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {combinedForIntake.length > 0 && (
            <div className="space-y-2 rounded border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-slate-900">
              <p className="text-xs font-medium text-gray-700 dark:text-gray-300">Submit one secret</p>
              <div className="flex flex-wrap gap-2">
                <select
                  value={selectedVar}
                  onChange={(e) => setSelectedVar(e.target.value)}
                  className="rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-slate-800"
                >
                  {combinedForIntake.map((m) => (
                    <option key={m.env_var} value={m.env_var}>
                      {m.env_var}
                    </option>
                  ))}
                </select>
                <input
                  type="password"
                  autoComplete="off"
                  value={secretValue}
                  onChange={(e) => setSecretValue(e.target.value)}
                  className="min-w-[200px] flex-1 rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-slate-800"
                  placeholder="Secret value (cleared after save)"
                />
              </div>
              <label className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
                <input
                  type="checkbox"
                  checked={persistSsm}
                  onChange={(e) => setPersistSsm(e.target.checked)}
                />
                Also persist to SSM when supported (recommended on AWS for GitHub App keys)
              </label>
              <button
                type="button"
                disabled={submitting || !secretValue.trim()}
                onClick={onSubmitOne}
                className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {submitting ? 'Saving…' : 'Save secret'}
              </button>
              {submitMsg && (
                <p className={`text-xs ${submitMsg.ok ? 'text-green-600' : 'text-red-600'}`}>{submitMsg.text}</p>
              )}
            </div>
          )}

          {recoveryInfo && (
            <div className="rounded border border-gray-200 bg-white p-3 text-xs dark:border-gray-700 dark:bg-slate-900">
              <p className="font-medium text-gray-700 dark:text-gray-300">Apply recovery (restart)</p>
              <p className="mt-1 text-gray-600 dark:text-gray-400">
                Automatic recreate only when the server sets ENABLE_SECRET_RECOVERY_AUTO_RESTART and
                DOCKER_COMPOSE_PROJECT_DIR (host repo path). No arbitrary commands.
              </p>
              <p className="mt-1 text-gray-600 dark:text-gray-400">
                Server: auto_restart={String(recoveryInfo.auto_restart_enabled)} · compose_project=
                {String(recoveryInfo.compose_project_configured)} · runnable={String(recoveryInfo.recovery_runnable)}
              </p>
              {canApplyRecovery && (
                <button
                  type="button"
                  disabled={applying || !adminKey.trim()}
                  onClick={runApplyRecovery}
                  className="mt-2 rounded bg-amber-700 px-3 py-1 text-xs text-white hover:bg-amber-800 disabled:opacity-50"
                >
                  {applying ? 'Applying…' : 'Apply & recreate backend-aws'}
                </button>
              )}
              {!recoveryInfo.recovery_runnable && (
                <p className="mt-2 text-amber-800 dark:text-amber-300">
                  Configure the host env for backend-aws, then reload. See docker-compose.yml (DOCKER_COMPOSE_PROJECT_DIR,
                  ENABLE_SECRET_RECOVERY_AUTO_RESTART).
                </p>
              )}
              {applyMsg && <p className="mt-2 text-gray-700 dark:text-gray-300">{applyMsg}</p>}
              {healthPollMsg && <p className="mt-1 text-green-700 dark:text-green-400">{healthPollMsg}</p>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
