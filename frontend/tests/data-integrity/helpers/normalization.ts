/**
 * Normalize boolean values from various formats to a standard boolean or null
 */
export function normalizeBoolean(value: unknown): boolean | null {
  if (value === null || value === undefined) {
    return null;
  }
  
  if (typeof value === 'boolean') {
    return value;
  }
  
  if (typeof value === 'number') {
    return value === 1;
  }
  
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (normalized === 'true' || normalized === '1' || normalized === 'yes' || normalized === 'enabled') {
      return true;
    }
    if (normalized === 'false' || normalized === '0' || normalized === 'no' || normalized === 'disabled') {
      return false;
    }
  }
  
  return null;
}

/**
 * Normalize status values to lowercase, trimmed string
 */
export function normalizeStatus(value: unknown): string {
  if (value === null || value === undefined) {
    return '';
  }
  
  if (typeof value === 'string') {
    return value.trim().toLowerCase();
  }
  
  return String(value).trim().toLowerCase();
}

/**
 * Normalize symbol to uppercase for consistent comparison
 */
export function normalizeSymbol(symbol: string): string {
  return symbol.trim().toUpperCase();
}

/**
 * Check if a value represents a true/enabled state (handles various formats)
 */
export function isEnabled(value: unknown): boolean {
  const normalized = normalizeBoolean(value);
  return normalized === true;
}

/**
 * Check if a value represents a false/disabled state (handles various formats)
 */
export function isDisabled(value: unknown): boolean {
  const normalized = normalizeBoolean(value);
  return normalized === false;
}










