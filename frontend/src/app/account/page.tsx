'use client';

import { useState, useEffect } from 'react';
import { getAccountBalance, AccountSummary } from '@/lib/api';

export default function AccountPage() {
  const [balance, setBalance] = useState<AccountSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exchange, setExchange] = useState<'CRYPTO_COM' | 'BINANCE'>('CRYPTO_COM');

  const fetchBalance = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const data = await getAccountBalance();
      // getAccountBalance returns an array, take the first one
      if (data && data.length > 0) {
        setBalance(data[0]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch balance');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBalance();
    // Auto-refresh every 30 seconds
    const interval = setInterval(fetchBalance, 30000);
    return () => clearInterval(interval);
     
  }, [exchange]);

  return (
    <div className="container mx-auto p-8">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">Account Balance</h1>
        <div className="flex gap-4 items-center">
          <select
            value={exchange}
            onChange={(e) => setExchange(e.target.value as 'CRYPTO_COM' | 'BINANCE')}
            className="border border-gray-300 rounded px-4 py-2"
            title="Select Exchange"
          >
            <option value="CRYPTO_COM">Crypto.com</option>
            <option value="BINANCE">Binance</option>
          </select>
          <button
            onClick={fetchBalance}
            disabled={loading}
            className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:bg-gray-400"
          >
            {loading ? 'Loading...' : 'Refresh'}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
          {error}
        </div>
      )}

      {balance && (
        <div className="space-y-6">
          <div className="bg-white border border-gray-300 rounded-lg overflow-hidden">
            <div className="bg-gray-100 px-6 py-4 border-b border-gray-300">
              <h2 className="text-xl font-semibold">Balance: {balance.currency}</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Currency
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Balance
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Available
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  <tr className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <div className="text-sm font-medium text-gray-900">{balance.currency}</div>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm text-gray-500">
                      {balance.balance}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm text-gray-500">
                      {balance.available}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {loading && !balance && (
        <div className="text-center py-12">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
          <p className="mt-4 text-gray-600">Loading account balance...</p>
        </div>
      )}
    </div>
  );
}

