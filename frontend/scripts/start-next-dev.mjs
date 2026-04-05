#!/usr/bin/env node
/**
 * Cross-platform wrapper to start Next.js dev server with configurable port.
 * Reads FRONTEND_PORT from .env.local or environment (defaults to 3001).
 */

import { spawn } from 'child_process';
import { readFileSync, existsSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const projectRoot = join(__dirname, '..');

// Load .env.local if it exists
function loadEnvLocal() {
  const envPath = join(projectRoot, '.env.local');
  if (!existsSync(envPath)) {
    return {};
  }
  
  const envContent = readFileSync(envPath, 'utf-8');
  const env = {};
  for (const line of envContent.split('\n')) {
    const trimmed = line.trim();
    if (trimmed && !trimmed.startsWith('#')) {
      const match = trimmed.match(/^([^=]+)=(.*)$/);
      if (match) {
        env[match[1].trim()] = match[2].trim();
      }
    }
  }
  return env;
}

// Read port from .env.local, then environment, then default to 3001
const envLocal = loadEnvLocal();
const port = process.env.FRONTEND_PORT || envLocal.FRONTEND_PORT || '3001';

console.log(`Starting Next.js dev server on port ${port}...`);

// Spawn next dev with the port
const nextDev = spawn('npx', ['next', 'dev', '-H', '0.0.0.0', '-p', port], {
  cwd: projectRoot,
  stdio: 'inherit',
  shell: false,
});

// Forward exit code
nextDev.on('exit', (code) => {
  process.exit(code || 0);
});

// Handle errors
nextDev.on('error', (err) => {
  console.error('Failed to start Next.js dev server:', err);
  process.exit(1);
});

