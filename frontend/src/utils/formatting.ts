/**
 * Formatting utility functions
 */

/**
 * Add thousand separators to a number string
 */
export function addThousandSeparators(numStr: string): string {
  const parts = numStr.split('.');
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return parts.join('.');
}

/**
 * Format numbers with correct decimals based on value magnitude
 */
export function formatNumber(num: number | null | undefined, symbol?: string): string {
  if (num === null || num === undefined) return '-';
  
  // If number is 0, return "0.00"
  if (num === 0) return '0.00';
  
  let formatted: string;
  
  // Adaptive rounding based on price magnitude (matching backend logic)
  if (num >= 100) {
    // High-value coins >= $100 - use 2 decimal places
    formatted = num.toFixed(2);
  } else if (num >= 1) {
    // Medium-value coins $1-$99 - use 2 decimal places
    formatted = num.toFixed(2);
  } else if (num >= 0.01) {
    // Low-value coins $0.01-$0.99 - use 6 decimal places
    formatted = num.toFixed(6);
  } else {
    // Very low-value coins < $0.01 - use 10 decimal places
    formatted = num.toFixed(10);
  }
  
  // For values < 0.01, preserve all decimal places (don't remove trailing zeros)
  if (num < 0.01) {
    return addThousandSeparators(formatted);
  }
  
  // For values >= 0.01, remove trailing zeros but preserve minimum decimals
  const parts = formatted.split('.');
  if (parts.length === 2) {
    // Determine minimum decimals to keep based on value magnitude
    let minDecimals = 2;
    if (num >= 100) {
      minDecimals = 2; // Values >= $100: keep at least 2 decimals
    } else if (num >= 1) {
      minDecimals = 2; // Values $1-$99: keep at least 2 decimals
    } else if (num >= 0.01) {
      minDecimals = 6; // Values $0.01-$0.99: keep at least 6 decimals
    }
    
    // Remove trailing zeros but keep at least minDecimals
    const decimals = parts[1].replace(/0+$/, '');
    if (decimals.length === 0) {
      // If all decimals were zeros, keep at least minDecimals
      formatted = parts[0] + '.' + parts[1].substring(0, Math.min(minDecimals, parts[1].length)).padEnd(Math.min(minDecimals, parts[1].length), '0');
    } else {
      // Keep meaningful decimals, but ensure at least minDecimals
      if (decimals.length < minDecimals) {
        formatted = parts[0] + '.' + decimals.padEnd(minDecimals, '0');
      } else {
        formatted = parts[0] + '.' + decimals;
      }
    }
  }
  
  // Add thousand separators
  return addThousandSeparators(formatted);
}

/**
 * Fixed-decimal formatter for P/L summary cards
 */
export function formatPLSummaryNumber(num: number | null | undefined): string {
  if (num === null || num === undefined) return '-';
  return addThousandSeparators((num ?? 0).toFixed(1));
}

/**
 * Format timestamps - uses browser's local timezone automatically
 */
export function formatTimestamp(ts?: number | string | Date): string {
  if (!ts) return 'N/A';
  let date: Date;
  
  if (ts instanceof Date) {
    date = ts;
  } else if (typeof ts === 'number') {
    // Timestamp in milliseconds - JavaScript Date interprets this as UTC
    date = new Date(ts);
  } else {
    // String - could be ISO format or custom format
    const str = String(ts);
    // If it's an ISO string (contains 'T' or ends with 'Z' or '+'), parse directly
    if (str.includes('T') || str.endsWith('Z') || str.includes('+') || str.includes('-', 10)) {
      date = new Date(str);
    } else {
      // Custom format like "2024-11-11 14:30:00 UTC" - treat as UTC
      // Remove "UTC" suffix and parse, then manually set as UTC
      const cleaned = str.replace(/\s+UTC$/, '').trim();
      if (cleaned.match(/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}/)) {
        // Format: YYYY-MM-DD HH:MM:SS - treat as UTC
        date = new Date(cleaned + 'Z'); // Add Z to indicate UTC
      } else {
        date = new Date(str);
      }
    }
  }
  
  if (isNaN(date.getTime())) return 'N/A';
  // Always use browser's local timezone with timezone name visible
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
    timeZoneName: 'short',
  });
}

/**
 * Format dates with time - always uses browser's local timezone
 */
export function formatDateTime(date: Date): string {
  if (!date || isNaN(date.getTime())) return 'N/A';
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
    timeZoneName: 'short',
  });
}

/**
 * Format time only - uses browser's local timezone
 */
export function formatTime(date: Date): string {
  if (!date || isNaN(date.getTime())) return 'Never';
  return date.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZoneName: 'short',
  });
}

/**
 * Normalize symbol keys to uppercase for consistent state access
 */
export function normalizeSymbolKey(symbol: string | undefined | null): string {
  return symbol ? symbol.toUpperCase() : '';
}



