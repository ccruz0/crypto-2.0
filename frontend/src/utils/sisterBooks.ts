/**
 * Dual USD/USDT book helpers — Crypto.com often lists both quotes for one base.
 */

export function parseInstrumentParts(
  instrument: string | null | undefined
): { base: string; quote: string } | null {
  const raw = (instrument || '').toUpperCase().trim();
  if (!raw) return null;
  if (raw.includes('_')) {
    const [base, quote] = raw.split('_');
    if (!base || !quote) return null;
    return { base, quote };
  }
  return { base: raw, quote: '' };
}

/** Sister quote for dual books (USD ↔ USDT). */
export function sisterQuote(quote: string): string | null {
  const q = (quote || '').toUpperCase();
  if (q === 'USD') return 'USDT';
  if (q === 'USDT') return 'USD';
  return null;
}

export function sisterInstrument(instrument: string | null | undefined): string | null {
  const parts = parseInstrumentParts(instrument);
  if (!parts?.quote) return null;
  const other = sisterQuote(parts.quote);
  if (!other) return null;
  return `${parts.base}_${other}`;
}

/** True when the sister USD/USDT instrument is also present in the list. */
export function hasSisterBook(
  instrument: string | null | undefined,
  instruments: Iterable<string | null | undefined>
): boolean {
  const sister = sisterInstrument(instrument);
  if (!sister) return false;
  const want = sister.toUpperCase();
  for (const item of instruments) {
    if ((item || '').toUpperCase() === want) return true;
  }
  return false;
}
