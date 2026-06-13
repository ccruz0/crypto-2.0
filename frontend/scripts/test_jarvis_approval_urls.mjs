#!/usr/bin/env node
/**
 * Sanity check: jarvisApproval.ts must not double-prefix /api when getApiUrl() already includes it.
 * Run: node frontend/scripts/test_jarvis_approval_urls.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const src = readFileSync(join(root, 'src/lib/jarvisApproval.ts'), 'utf8');

const bad = [...src.matchAll(/`\$\{API\}\/api\/jarvis/g)];
if (bad.length > 0) {
  console.error(`FAIL: jarvisApproval.ts double-prefixes /api (${bad.length} occurrence(s))`);
  process.exit(1);
}

const good = [...src.matchAll(/`\$\{API\}\/jarvis/g)];
if (good.length < 5) {
  console.error(`FAIL: expected at least 5 /jarvis paths, found ${good.length}`);
  process.exit(1);
}

console.log('OK: jarvisApproval.ts uses /jarvis paths without double /api prefix');
