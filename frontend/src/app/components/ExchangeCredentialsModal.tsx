'use client';

import { useState } from 'react';
import { getApiUrl } from '@/lib/environment';

type Props = {
  isOpen: boolean;
  onClose: () => void;
  onSaved?: () => void;
};

export default function ExchangeCredentialsModal({
  isOpen,
  onClose,
  onSaved,
}: Props) {
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [adminKey, setAdminKey] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  async function handleSave() {
    setLoading(true);
    setError(null);

    try {
      const apiUrl = getApiUrl();
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (adminKey.trim()) headers['X-Admin-Key'] = adminKey.trim();
      const res = await fetch(`${apiUrl}/settings/exchange-credentials`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          api_key: apiKey,
          api_secret: apiSecret,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Failed to save credentials');
      }

      setApiKey('');
      setApiSecret('');
      onSaved?.();
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to save credentials');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-gray-800 rounded-xl w-full max-w-md p-6 shadow-xl">
        <h2 className="text-lg font-semibold mb-4 text-gray-900 dark:text-white">
          Add Exchange API Credentials
        </h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
          Backend must be restarted for new credentials to take effect. Portfolio sync will run after restart.
        </p>

        <input
          type="text"
          placeholder="API Key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          className="w-full border border-gray-300 dark:border-gray-600 rounded p-2 mb-3 bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-500"
          autoComplete="off"
        />

        <input
          type="password"
          placeholder="API Secret"
          value={apiSecret}
          onChange={(e) => setApiSecret(e.target.value)}
          className="w-full border border-gray-300 dark:border-gray-600 rounded p-2 mb-3 bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-500"
          autoComplete="new-password"
        />

        <input
          type="password"
          placeholder="Admin key (required if ADMIN_ACTIONS_KEY is set)"
          value={adminKey}
          onChange={(e) => setAdminKey(e.target.value)}
          className="w-full border border-gray-300 dark:border-gray-600 rounded p-2 mb-3 bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-500"
          autoComplete="off"
        />

        {error && (
          <div className="text-red-600 dark:text-red-400 text-sm mb-3">{error}</div>
        )}

        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={loading}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
