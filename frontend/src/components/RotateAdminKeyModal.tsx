'use client';

import React, { useState, useEffect } from 'react';
import { rotateAdminKey } from '@/lib/api';

type Props = {
  isOpen: boolean;
  onClose: () => void;
  currentAdminKey: string;
  onRotated: (newKey: string) => void | Promise<void>;
};

/**
 * Modal: verify current admin key (already used for API), set a new ADMIN_ACTIONS_KEY
 * (persisted server-side to runtime.env + in-process env).
 */
export default function RotateAdminKeyModal({ isOpen, onClose, currentAdminKey, onRotated }: Props) {
  const [newKey, setNewKey] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setNewKey('');
    setConfirm('');
    setError(null);
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async () => {
    if (!currentAdminKey.trim()) {
      setError('Current admin key is required.');
      return;
    }
    const a = newKey.trim();
    const b = confirm.trim();
    if (a.length < 16) {
      setError('New key must be at least 16 characters.');
      return;
    }
    if (a !== b) {
      setError('New key and confirmation do not match.');
      return;
    }
    if (a === currentAdminKey.trim()) {
      setError('New key must differ from the current key.');
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await rotateAdminKey(currentAdminKey.trim(), a);
      await onRotated(a);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to rotate admin key');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="rotate-admin-key-title"
    >
      <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-4 shadow-xl dark:border-gray-600 dark:bg-slate-900">
        <h2 id="rotate-admin-key-title" className="text-sm font-semibold text-gray-900 dark:text-white">
          Change admin key
        </h2>
        <p className="mt-2 text-xs text-gray-600 dark:text-gray-400">
          Enter a new strong key (min. 16 characters). It replaces <span className="font-mono">ADMIN_ACTIONS_KEY</span>{' '}
          in <span className="font-mono">runtime.env</span> and takes effect immediately for this server process. Copy the
          new key somewhere safe before closing.
        </p>
        <label className="mt-3 block text-xs font-medium text-gray-700 dark:text-gray-300">
          New admin key
          <input
            type="password"
            autoComplete="new-password"
            value={newKey}
            onChange={(e) => {
              setNewKey(e.target.value);
              setError(null);
            }}
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-xs dark:border-gray-600 dark:bg-slate-800"
            placeholder="At least 16 characters"
          />
        </label>
        <label className="mt-2 block text-xs font-medium text-gray-700 dark:text-gray-300">
          Confirm new admin key
          <input
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => {
              setConfirm(e.target.value);
              setError(null);
            }}
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-xs dark:border-gray-600 dark:bg-slate-800"
          />
        </label>
        {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            disabled={submitting}
            onClick={onClose}
            className="rounded border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-slate-800"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={submitting}
            onClick={() => void handleSubmit()}
            className="rounded bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-black disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
          >
            {submitting ? 'Saving…' : 'Save new key'}
          </button>
        </div>
      </div>
    </div>
  );
}
