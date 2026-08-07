import { describe, expect, it, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, writeFileSync, rmSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';

describe('internalApiProxyServer', () => {
  const envBackup: Record<string, string | undefined> = {};

  beforeEach(() => {
    envBackup.ATP_API_KEY = process.env.ATP_API_KEY;
    envBackup.INTERNAL_API_KEY = process.env.INTERNAL_API_KEY;
    envBackup.BACKEND_URL = process.env.BACKEND_URL;
  });

  afterEach(() => {
    for (const [k, v] of Object.entries(envBackup)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  });

  it('reads ATP_API_KEY via dynamic env access', async () => {
    process.env.ATP_API_KEY = 'test-runtime-key';
    const { getBackendApiKey } = await import('@/lib/internalApiProxyServer');
    expect(getBackendApiKey()).toBe('test-runtime-key');
  });

  it('falls back to demo-key when unset', async () => {
    delete process.env.ATP_API_KEY;
    delete process.env.INTERNAL_API_KEY;
    const dir = mkdtempSync(join(tmpdir(), 'atp-runtime-'));
    writeFileSync(join(dir, 'empty.env'), '# no keys\n');
    const { getBackendApiKey } = await import('@/lib/internalApiProxyServer');
    expect(getBackendApiKey()).toBe('demo-key');
    rmSync(dir, { recursive: true, force: true });
  });
});
