#!/usr/bin/env node
/**
 * Chrome Console Error Scanner
 * 
 * This script:
 * 1. Launches Chromium programmatically using Playwright
 * 2. Opens the dashboard URL (default: http://localhost:3000)
 * 3. Collects JavaScript console errors and page errors
 * 4. Writes errors to tmp/chrome-console-errors.json
 * 
 * Base URL: Can be set via DASHBOARD_URL env var or defaults to http://localhost:3000
 */

import { chromium, Browser, Page } from 'playwright';
import * as fs from 'fs';
import * as path from 'path';

interface ConsoleError {
  type: string;
  message: string;
  location?: {
    url?: string;
    line?: number;
    column?: number;
  };
  stack?: string;
  timestamp?: string;
}

const BASE_URL = process.env.DASHBOARD_URL || 'http://localhost:3000';
const OUTPUT_FILE = path.join(__dirname, '..', 'tmp', 'chrome-console-errors.json');
const TIMEOUT = 20000; // 20 seconds timeout for page load

async function scanChromeConsole(): Promise<void> {
  const errors: ConsoleError[] = [];
  let browser: Browser | null = null;

  try {
    console.log(`🔍 Starting Chrome console scan...`);
    console.log(`📡 Dashboard URL: ${BASE_URL}`);
    console.log(`⏱️  Timeout: ${TIMEOUT}ms`);

    // Launch Chromium
    browser = await chromium.launch({
      headless: true, // Run headless for automation
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });

    const context = await browser.newContext();
    const page = await context.newPage();

    // Listen for console errors
    page.on('console', (msg) => {
      const type = msg.type();
      if (type === 'error') {
        const text = msg.text();
        const location = msg.location();
        errors.push({
          type: 'console_error',
          message: text,
          location: {
            url: location.url,
            line: location.lineNumber,
            column: location.columnNumber,
          },
          timestamp: new Date().toISOString(),
        });
      }
    });

    // Listen for page errors (uncaught exceptions)
    page.on('pageerror', (error) => {
      errors.push({
        type: 'page_error',
        message: error.message,
        stack: error.stack,
        timestamp: new Date().toISOString(),
      });
    });

    // Listen for request failures
    page.on('requestfailed', (request) => {
      const failure = request.failure();
      if (failure) {
        errors.push({
          type: 'request_failed',
          message: `Request failed: ${request.method()} ${request.url()}`,
          location: {
            url: request.url(),
          },
          stack: failure.errorText,
          timestamp: new Date().toISOString(),
        });
      }
    });

    console.log(`🌐 Navigating to ${BASE_URL}...`);
    
    // Navigate to the dashboard and wait for network idle or timeout
    try {
      await page.goto(BASE_URL, {
        waitUntil: 'networkidle',
        timeout: TIMEOUT,
      });
    } catch (err) {
      console.warn(`⚠️  Page load timeout or error: ${err instanceof Error ? err.message : String(err)}`);
      // Continue anyway to capture errors
    }

    // Wait a bit for JavaScript to execute and any async errors to surface
    console.log(`⏳ Waiting for JavaScript execution...`);
    await page.waitForTimeout(3000);

    // Try to wait for any React hydration or component errors
    try {
      await page.waitForFunction(
        () => {
          // Check if page is loaded by looking for common dashboard elements
          return document.readyState === 'complete';
        },
        { timeout: 5000 }
      );
    } catch (err) {
      // Ignore timeout, continue
    }

    console.log(`✅ Page loaded. Captured ${errors.length} error(s).`);

    // Ensure tmp directory exists
    const outputDir = path.dirname(OUTPUT_FILE);
    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true });
    }

    // Write errors to file
    fs.writeFileSync(OUTPUT_FILE, JSON.stringify(errors, null, 2), 'utf-8');
    console.log(`📄 Errors written to: ${OUTPUT_FILE}`);
    console.log(`📊 Total errors found: ${errors.length}`);

    if (errors.length > 0) {
      console.log(`\n🔴 Errors detected:`);
      errors.forEach((error, idx) => {
        console.log(`  ${idx + 1}. [${error.type}] ${error.message}`);
        if (error.location?.url) {
          console.log(`     Location: ${error.location.url}:${error.location.line}:${error.location.column}`);
        }
      });
    } else {
      console.log(`\n✅ No errors found!`);
    }

  } catch (err) {
    console.error(`❌ Error during scan: ${err instanceof Error ? err.message : String(err)}`);
    console.error(err);
    process.exit(1);
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}

// Run the scanner
scanChromeConsole()
  .then(() => {
    console.log(`\n✅ Scan complete.`);
    process.exit(0);
  })
  .catch((err) => {
    console.error(`\n❌ Scan failed: ${err instanceof Error ? err.message : String(err)}`);
    console.error(err);
    process.exit(1);
  });

