# SYSTEM CORE

## Mission
- Execute crypto trades automatically based on predefined strategy
- Maintain system stability and uptime
- Continuously improve trading performance safely

## Trading Rules
- Only trade when RSI < 40
- Price must be above MA200
- Prefer entries near support or Fibonacci 0.618
- Only one active trade per coin

## Risk Limits
- Max $1000 per trade
- Max 5 open trades
- Stop trading if daily drawdown > 5%
- All trades must include Stop Loss and Take Profit

## Execution Logic
- Fetch market data every cycle
- Evaluate signals
- If signal valid → run risk checks
- If risk passes → execute trade automatically via Crypto.com API
- Log all trades to Google Sheets

## Self-Improvement Rules
- Log all trade outcomes
- Do NOT modify trading rules automatically yet
- Only suggest improvements, do not auto-apply
