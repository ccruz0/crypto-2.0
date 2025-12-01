# Debug Strategy Script

## Purpose

Quickly inspect strategy decision logs for a specific symbol to diagnose BUY→WAIT flips.

## Usage

### Basic Usage
```bash
# Show last 20 strategy logs for ALGO_USDT
python backend/scripts/debug_strategy.py ALGO_USDT

# Show last 50 logs
python backend/scripts/debug_strategy.py ALGO_USDT --last 50

# Only show BUY decisions
python backend/scripts/debug_strategy.py ALGO_USDT --grep "decision=BUY"

# Compare consecutive entries to find flips
python backend/scripts/debug_strategy.py ALGO_USDT --compare
```

### Docker Container
```bash
# Use a different container name
python backend/scripts/debug_strategy.py ALGO_USDT --container my-backend-container
```

## Output

The script shows:
- **Raw Values (unrounded)**: price, RSI, buy_target, volume_ratio, MAs
- **Buy Flags**: All `buy_*` reasons with True/False/None status
- **Flip Detection**: When `--compare` is used, shows which flag flipped and the numeric values that caused it

## Example Output

```
Entry #1 - ALGO_USDT
Decision: BUY | Buy Signal: True

Raw Values (unrounded):
  price:        0.14280500
  rsi:          35.0000
  buy_target:   0.14281000
  price - target: -0.00000500 ✓
  volume_ratio: 1.200000

Buy Flags:
  buy_target_ok      = True  ✓
  buy_rsi_ok         = True  ✓
  ...

⚠️  FLIP DETECTED between Entry #1 and Entry #2
   BUY → WAIT
   buy_signal: True → False

   Flags that flipped:
     buy_target_ok: True → False
       ⚠️  This flag going False caused BUY → WAIT!
       Entry #1: price=0.14280500, buy_target=0.14281000, diff=-0.00000500
       Entry #2: price=0.14282100, buy_target=0.14281000, diff=+0.00001100
```

## Integration with Docker Logs

The script uses `docker logs` internally, but you can also use docker directly:

```bash
docker logs automated-trading-platform-backend-aws-1 --tail 10000 | \
  grep DEBUG_STRATEGY_FINAL | grep ALGO_USDT | tail -20
```

## Next Steps

After identifying the flip:
1. Document it in `docs/buy_flip_example_ALGO_USDT.md`
2. Analyze if hysteresis would help
3. Design tolerance thresholds
4. Implement if approved

