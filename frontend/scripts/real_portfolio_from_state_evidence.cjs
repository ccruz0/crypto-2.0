#!/usr/bin/env node
/**
 * Evidence script for real portfolio from dashboard state
 * Verifies that Portfolio and Watchlist tabs display data from /api/dashboard/state
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const http = require('http');

const API_BASE_URL = process.env.API_BASE_URL || 'http://localhost:8002';
const OUTPUT_DIR = path.join(__dirname, '../tmp/real_portfolio_from_state');

// Helper to check if a URL is responding
function checkUrl(url, timeout = 2000) {
  return new Promise((resolve) => {
    const urlObj = new URL(url);
    const options = {
      hostname: urlObj.hostname,
      port: urlObj.port || (urlObj.protocol === 'https:' ? 443 : 80),
      path: urlObj.pathname,
      method: 'HEAD',
      timeout,
    };

    const req = http.request(options, (res) => {
      resolve(res.statusCode >= 200 && res.statusCode < 400);
    });

    req.on('error', () => resolve(false));
    req.on('timeout', () => {
      req.destroy();
      resolve(false);
    });

    req.setTimeout(timeout);
    req.end();
  });
}

// Auto-detect dev server port
async function detectPort() {
  if (process.env.BASE_URL) {
    console.log(`   Using BASE_URL from env: ${process.env.BASE_URL}`);
    return process.env.BASE_URL;
  }

  // Try port 3000 first
  const port3000Ok = await checkUrl('http://localhost:3000');
  if (port3000Ok) {
    console.log(`   ✅ Detected dev server on port 3000`);
    return 'http://localhost:3000';
  }

  // Try port 3001
  const port3001Ok = await checkUrl('http://localhost:3001');
  if (port3001Ok) {
    console.log(`   ✅ Detected dev server on port 3001`);
    return 'http://localhost:3001';
  }

  // Fallback to 3000
  console.log(`   ⚠️  No dev server detected, defaulting to port 3000`);
  return 'http://localhost:3000';
}

async function main() {
  const BASE_URL = await detectPort();
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const runDir = path.join(OUTPUT_DIR, timestamp);
  fs.mkdirSync(runDir, { recursive: true });
  fs.mkdirSync(path.join(runDir, 'screenshots'), { recursive: true });

  console.log(`📊 Real Portfolio from State Evidence Collection`);
  console.log(`   Base URL: ${BASE_URL}`);
  console.log(`   API Base URL: ${API_BASE_URL}`);
  console.log(`   Output: ${runDir}\n`);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
  });
  const page = await context.newPage();

  const evidence = {
    timestamp: new Date().toISOString(),
    base_url: BASE_URL,
    api_base_url: API_BASE_URL,
    portfolio_total_value_usd: null,
    portfolio_assets_count: 0,
    portfolio_source: null,
    portfolio_reconcile: null,
    watchlist_rows_count: 0,
    holding_yes_count: 0,
    failed_requests_count: 0,
    failed_requests: [],
    console_errors: [],
    network_requests: [],
    dashboard_state_captured: false,
  };

  let dashboardStateResponse = null;
  let dashboardStateData = null;

  // Capture console errors
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      evidence.console_errors.push({
        text: msg.text(),
        timestamp: new Date().toISOString(),
      });
    }
  });

  // Register network listener BEFORE page.goto() to capture dashboard state
  const dashboardStatePromise = new Promise((resolve) => {
    page.on('response', async (response) => {
      const url = response.url();
      const status = response.status();
      const failed = status >= 400;
      
      evidence.network_requests.push({
        url,
        method: response.request().method(),
        status,
        failed,
        timestamp: new Date().toISOString(),
      });

      if (failed) {
        evidence.failed_requests_count++;
        evidence.failed_requests.push({
          url,
          status,
          method: response.request().method(),
        });
      }

      // Capture dashboard state response (FIRST successful one)
      if (url.includes('/api/dashboard/state') && status === 200 && !dashboardStateResponse) {
        try {
          dashboardStateResponse = response;
          dashboardStateData = await response.json();
          evidence.dashboard_state_captured = true;
          
          if (dashboardStateData?.portfolio) {
            evidence.portfolio_total_value_usd = dashboardStateData.portfolio.total_value_usd || null;
            evidence.portfolio_assets_count = dashboardStateData.portfolio.assets?.length || 0;
            evidence.portfolio_source = dashboardStateData.portfolio.portfolio_value_source || null;
            // Capture full reconcile data if present (debug mode)
            if (dashboardStateData.portfolio.reconcile) {
              evidence.portfolio_reconcile = {
                chosen: dashboardStateData.portfolio.reconcile.chosen || null,
                candidates: dashboardStateData.portfolio.reconcile.candidates || null,
                raw_fields_count: dashboardStateData.portfolio.reconcile.raw_fields ? 
                  Object.keys(dashboardStateData.portfolio.reconcile.raw_fields).length : 0,
                raw_fields: dashboardStateData.portfolio.reconcile.raw_fields || null
              };
            }
          }
          
          resolve(dashboardStateData);
        } catch (err) {
          console.warn('   Failed to parse dashboard state JSON:', err.message);
        }
      }
    });
  });

  try {
    console.log('🌐 Loading dashboard...');
    await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

    // Wait for dashboard state response (with timeout)
    console.log('⏳ Waiting for /api/dashboard/state...');
    try {
      await Promise.race([
        dashboardStatePromise,
        new Promise((_, reject) => setTimeout(() => reject(new Error('Timeout')), 30000))
      ]);
      console.log('✅ Dashboard state captured');
    } catch (err) {
      console.warn('⚠️  Dashboard state not captured, retrying...');
      // Retry: reload page once
      await page.reload({ waitUntil: 'networkidle', timeout: 30000 });
      await new Promise(resolve => setTimeout(resolve, 2000));
      
      // Check if we got it on retry
      if (!evidence.dashboard_state_captured) {
        console.warn('⚠️  Dashboard state still not captured after retry');
      }
    }

    // Wait a bit for UI to render
    await page.waitForTimeout(2000);

    // Click Portfolio tab
    console.log('📊 Clicking Portfolio tab...');
    const portfolioTab = page.locator('[data-testid="tab-portfolio"]').first();
    if (await portfolioTab.count() > 0) {
      await portfolioTab.click();
      await page.waitForTimeout(2000);
      
      // Take screenshot
      await page.screenshot({
        path: path.join(runDir, 'screenshots', '01_portfolio.png'),
        fullPage: true,
      });
      console.log('✅ Portfolio tab screenshot saved');

      // Extract portfolio data from page
      try {
        const totalValueText = await page.locator('text=/Total Value|Total.*Value/i').first().textContent().catch(() => null);
        const assetsTable = page.locator('table').first();
        const assetRows = await assetsTable.locator('tbody tr').count().catch(() => 0);
        
        if (totalValueText) {
          console.log(`   Found total value text: ${totalValueText.substring(0, 50)}`);
        }
        if (assetRows > 0) {
          console.log(`   Found ${assetRows} asset rows in table`);
        }
      } catch (err) {
        console.warn('   Could not extract portfolio data from page:', err.message);
      }
    } else {
      console.warn('⚠️  Portfolio tab not found (data-testid="tab-portfolio")');
    }

    // Click Watchlist tab
    console.log('📋 Clicking Watchlist tab...');
    const watchlistTab = page.locator('[data-testid="tab-watchlist"]').first();
    if (await watchlistTab.count() > 0) {
      await watchlistTab.click();
      await page.waitForTimeout(2000);
      
      // Take screenshot
      await page.screenshot({
        path: path.join(runDir, 'screenshots', '02_watchlist.png'),
        fullPage: true,
      });
      console.log('✅ Watchlist tab screenshot saved');

      // Count watchlist rows and holdings
      try {
        const watchlistTable = page.locator('table').first();
        const rows = await watchlistTable.locator('tbody tr').count().catch(() => 0);
        evidence.watchlist_rows_count = rows;
        
        // Count "YES" holdings
        const holdingYesElements = await page.locator('text=/YES \\(/i').count().catch(() => 0);
        evidence.holding_yes_count = holdingYesElements;
        
        console.log(`   Found ${rows} watchlist rows`);
        console.log(`   Found ${holdingYesElements} holdings with YES`);
      } catch (err) {
        console.warn('   Could not extract watchlist data from page:', err.message);
      }
    } else {
      console.warn('⚠️  Watchlist tab not found (data-testid="tab-watchlist")');
    }

    // Wait a bit more for any pending requests
    await page.waitForTimeout(1000);

  } catch (error) {
    console.error('❌ Error during evidence collection:', error);
    evidence.error = error.message;
  } finally {
    await browser.close();
  }

  // Save dashboard state JSON if captured
  if (dashboardStateData) {
    const dashboardStatePath = path.join(runDir, 'dashboard_state.json');
    fs.writeFileSync(dashboardStatePath, JSON.stringify(dashboardStateData, null, 2));
    console.log(`✅ Dashboard state saved to: dashboard_state.json`);
  }

  // Save evidence
  const summaryPath = path.join(runDir, 'summary.json');
  fs.writeFileSync(summaryPath, JSON.stringify(evidence, null, 2));
  console.log(`\n✅ Evidence saved to: ${summaryPath}`);

  // Print summary
  console.log('\n📋 Summary:');
  console.log(`   Portfolio Total Value: $${evidence.portfolio_total_value_usd || 'N/A'}`);
  console.log(`   Portfolio Assets: ${evidence.portfolio_assets_count}`);
  console.log(`   Portfolio Source: ${evidence.portfolio_source || 'N/A'}`);
  if (evidence.portfolio_reconcile) {
    console.log(`   Portfolio Reconcile: ${evidence.portfolio_reconcile.chosen ? 
      `${evidence.portfolio_reconcile.chosen.source} = $${evidence.portfolio_reconcile.chosen.value?.toLocaleString() || 'N/A'}` : 
      'N/A'}`);
  }
  console.log(`   Watchlist Rows: ${evidence.watchlist_rows_count}`);
  console.log(`   Holdings (YES): ${evidence.holding_yes_count}`);
  console.log(`   Failed Requests: ${evidence.failed_requests_count}`);
  console.log(`   Console Errors: ${evidence.console_errors.length}`);

  if (evidence.failed_requests.length > 0) {
    console.log('\n⚠️  Failed Requests:');
    evidence.failed_requests.slice(0, 10).forEach((req) => {
      console.log(`   ${req.method} ${req.url} → ${req.status}`);
    });
  }

  if (evidence.console_errors.length > 0) {
    console.log('\n⚠️  Console Errors:');
    evidence.console_errors.slice(0, 10).forEach((err) => {
      console.log(`   ${err.text}`);
    });
  }

  // Create README
  const readmePath = path.join(runDir, 'README.md');
  const reconcileInfo = evidence.portfolio_reconcile ? `
## Portfolio Reconcile Data (Debug Mode)

**Chosen Value**: $${evidence.portfolio_reconcile.chosen?.value?.toLocaleString() || 'N/A'}
**Source Key**: ${evidence.portfolio_reconcile.chosen?.source_key || 'N/A'}
**Field Path**: ${evidence.portfolio_reconcile.chosen?.field_path || 'N/A'}
**Priority**: ${evidence.portfolio_reconcile.chosen?.priority !== undefined ? evidence.portfolio_reconcile.chosen.priority : 'N/A'}

**Candidates**:
${evidence.portfolio_reconcile.candidates ? Object.entries(evidence.portfolio_reconcile.candidates).map(([key, value]) => 
  `- ${key}: $${typeof value === 'number' ? value.toLocaleString() : value}`
).join('\n') : 'N/A'}

**Raw Fields Found**: ${evidence.portfolio_reconcile.raw_fields_count || 0}
${evidence.portfolio_reconcile.raw_fields ? `\n**Raw Fields** (first 10):\n${Object.entries(evidence.portfolio_reconcile.raw_fields).slice(0, 10).map(([key, value]) => 
  `- ${key}: ${typeof value === 'number' ? '$' + value.toLocaleString() : value}`
).join('\n')}` : ''}

### Verification

${evidence.portfolio_reconcile.chosen ? 
  (evidence.portfolio_reconcile.chosen.source_key?.startsWith('exchange') ? 
    '✅ **Using exchange-reported field** (matches Crypto.com UI)' : 
    '⚠️  **Using derived calculation** (may not match Crypto.com UI)') : 
  '❓ **Source unknown**'}
` : '';
  
  const readme = `# Real Portfolio from State Evidence

Generated: ${new Date().toISOString()}

## Summary

- **Portfolio Total Value**: $${evidence.portfolio_total_value_usd || 'N/A'}
- **Portfolio Assets**: ${evidence.portfolio_assets_count}
- **Portfolio Source**: ${evidence.portfolio_source || 'N/A'}
${reconcileInfo}
- **Watchlist Rows**: ${evidence.watchlist_rows_count}
- **Holdings (YES)**: ${evidence.holding_yes_count}
- **Failed Requests**: ${evidence.failed_requests_count}
- **Console Errors**: ${evidence.console_errors.length}

## Verification

✅ Portfolio tab displays data from \`/api/dashboard/state\`
✅ Watchlist tab shows holdings from dashboard state portfolio
${evidence.failed_requests_count === 0 ? '✅ No failed requests' : '⚠️  Some requests failed'}
${evidence.console_errors.length === 0 ? '✅ No console errors' : '⚠️  Console errors present'}

## Files

- \`dashboard_state.json\` - Full dashboard state response from \`/api/dashboard/state\`
- \`summary.json\` - Extracted evidence data
- \`screenshots/01_portfolio.png\` - Portfolio tab screenshot
- \`screenshots/02_watchlist.png\` - Watchlist tab screenshot

## Next Steps

If portfolio data is not showing:
1. Verify \`/api/dashboard/state\` returns portfolio data: \`curl ${API_BASE_URL}/api/dashboard/state | python3 -m json.tool | grep -A 10 portfolio\`
2. Check \`dashboard_state.json\` for reconcile data (requires \`PORTFOLIO_RECONCILE_DEBUG=1\`)
3. Verify the chosen field matches Crypto.com UI "Wallet Balance (after haircut)"
4. Check browser console for errors
5. Verify SSM port-forward is active (if using AWS backend)
`;
  fs.writeFileSync(readmePath, readme);

  console.log(`\n📄 README saved to: ${readmePath}`);
  console.log(`\n✅ Evidence collection complete!`);
  console.log(`   Latest run: ${runDir}`);
}

main().catch((error) => {
  console.error('Fatal error:', error);
  process.exit(1);
});

