import * as fs from 'fs';
import * as path from 'path';
import type { Page } from '@playwright/test';

export interface Discrepancy {
  tabName: string;
  timestamp: string;
  symbol: string;
  field: string;
  uiValue: unknown;
  apiValue: unknown;
  apiSourceUrl: string;
}

/**
 * Write discrepancy report to JSON file
 */
export function writeDiscrepancyReport(tabName: string, discrepancies: Discrepancy[]): void {
  if (discrepancies.length === 0) {
    return;
  }
  
  const reportsDir = path.join(process.cwd(), 'test-results', 'data-integrity');
  
  // Ensure directory exists
  if (!fs.existsSync(reportsDir)) {
    fs.mkdirSync(reportsDir, { recursive: true });
  }
  
  const reportPath = path.join(reportsDir, `${tabName}-discrepancies.json`);
  
  const report = {
    tabName,
    timestamp: new Date().toISOString(),
    discrepancyCount: discrepancies.length,
    discrepancies
  };
  
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
  console.log(`📝 Discrepancy report written: ${reportPath}`);
}

/**
 * Capture API responses from network requests
 */
export interface ApiResponse {
  url: string;
  method: string;
  status: number;
  body: unknown;
  timestamp: number;
}

export class ApiCapture {
  private responses: ApiResponse[] = [];
  
  constructor(private page: Page) {
    this.setupListeners();
  }
  
  private setupListeners(): void {
    this.page.on('response', async (response) => {
      const url = response.url();
      const method = response.request().method();
      const status = response.status();
      
      // Only capture API responses
      if (!url.includes('/api/')) {
        return;
      }
      
      try {
        // Try to parse as JSON
        const body = await response.json().catch(() => null);
        
        this.responses.push({
          url,
          method,
          status,
          body,
          timestamp: Date.now()
        });
      } catch (error) {
        // Skip if we can't parse the response
      }
    });
  }
  
  /**
   * Get all captured API responses
   */
  getResponses(): ApiResponse[] {
    return [...this.responses];
  }
  
  /**
   * Get API responses matching a URL pattern
   */
  getResponsesByPattern(pattern: string | RegExp): ApiResponse[] {
    const regex = typeof pattern === 'string' ? new RegExp(pattern) : pattern;
    return this.responses.filter(r => regex.test(r.url));
  }
  
  /**
   * Get the most recent API response for a URL pattern
   */
  getLatestResponse(pattern: string | RegExp): ApiResponse | null {
    const matching = this.getResponsesByPattern(pattern);
    if (matching.length === 0) {
      return null;
    }
    // Return the most recent (last in array)
    return matching[matching.length - 1];
  }
  
  /**
   * Clear captured responses
   */
  clear(): void {
    this.responses = [];
  }
}

