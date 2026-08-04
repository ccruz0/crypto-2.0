/**
 * Server-only helpers for /internal-api proxy (never import from client components).
 */
import { readFileSync, existsSync } from 'fs';

function readEnv(key: string): string {
  // Bracket access avoids Next.js build-time inlining of undefined secrets.
  const v = process.env[key];
  return typeof v === 'string' ? v.trim() : '';
}

function readKeyFromRuntimeEnvFile(): string {
  const paths = ['/run/secrets/runtime.env', '/app/secrets/runtime.env'];
  for (const filePath of paths) {
    if (!existsSync(filePath)) continue;
    try {
      const text = readFileSync(filePath, 'utf8');
      for (const line of text.split('\n')) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('#')) continue;
        const eq = trimmed.indexOf('=');
        if (eq <= 0) continue;
        const name = trimmed.slice(0, eq).trim();
        if (name !== 'ATP_API_KEY' && name !== 'INTERNAL_API_KEY') continue;
        let val = trimmed.slice(eq + 1).trim();
        if (
          (val.startsWith('"') && val.endsWith('"')) ||
          (val.startsWith("'") && val.endsWith("'"))
        ) {
          val = val.slice(1, -1);
        }
        if (val) return val;
      }
    } catch {
      // try next path
    }
  }
  return '';
}

export function getBackendApiKey(): string {
  return (
    readEnv('ATP_API_KEY') ||
    readEnv('INTERNAL_API_KEY') ||
    readKeyFromRuntimeEnvFile() ||
    'demo-key'
  );
}

export function getBackendBaseUrl(): string {
  return (readEnv('BACKEND_URL') || 'http://localhost:8002').replace(/\/$/, '');
}
