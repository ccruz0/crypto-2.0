# Local scripts

**zsh users:** Create these scripts as files and run them (e.g. `bash scripts/local/run_trigger_probe_matrix.sh`). Do not paste script contents at the terminal prompt—pasting can trigger history expansion and alter `!` characters. If you must paste, run `set +H` first to disable history expansion.

---

## Trigger probe matrix

Runs the Crypto.com trigger probe for ETH_USDT with **SELL** then **BUY**, saving each run’s stdout to `/tmp` and extracting: `correlation_id`, `jsonl_path`, group counts by (http_status, code, message), `ORDER_ID_BUT_REJECTED (code=220)` (if present), and `filtered_invalid_side_rule` (if present). Prints the two JSONL paths at the end.

**Defaults:** instrument ETH_USDT, qty 0.003, ref-price 2950, max-variants 50. Logs: `/tmp/trigger_probe_matrix_<SELL|BUY>_<timestamp>.log`.

**Make executable (optional):**
```bash
chmod +x scripts/local/run_trigger_probe_matrix.sh
chmod +x scripts/local/analyze_trigger_probe_jsonl.py
```

**Run matrix:**
```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/local/run_trigger_probe_matrix.sh
```

---

## Trigger probe JSONL analyzer

Reads one or more probe JSONL files (paths or globs). Outputs: totals by schema; by schema + (http_status, code, message) top 20; by schema + (order_type, side) top 20; counts for `filtered_invalid_side_rule`, exceptions, and `verified_exists` true/false/missing. Success = `verified_exists == True` and `code in {0, None, 140001}`; `code=220` is always a hard failure. Winner heuristic: schema with most success, then fewer fail_220, then fewer other failures; `unknown` schema is excluded from winner if other schemas exist.

**Run analyzer:**
```bash
cd /Users/carloscruz/automated-trading-platform
python3 scripts/local/analyze_trigger_probe_jsonl.py /tmp/crypto_trigger_probe_*.jsonl
```

**Exit codes:** 0 if at least one file parsed; 2 if no files found or all unreadable.
