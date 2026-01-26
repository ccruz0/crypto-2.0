# Contributing: Small Changes Guide

This guide helps prevent accidental large refactors when making small, targeted changes.

## What is a "Small Change"?

A **small change** in this repository means:
- Environment check replacements (e.g., `os.getenv("ENVIRONMENT")` → `is_aws()`)
- Log message tweaks
- Tiny bugfixes (1-3 lines)
- Documentation updates
- Configuration alignment

**Expected diff size**: Under ~50 lines per file, unless explicitly requested otherwise.

## What is NOT a Small Change?

**Explicitly banned** in small-change commits:
- Function/class renames
- Function signature changes (adding/removing parameters)
- Whitespace-only file rewrites
- Large refactors across multiple modules
- Restructuring return shapes or data formats
- Removing helper methods or adding new abstractions

## Before You Commit Checklist

Run these commands before committing a small change:

```bash
# 1. Check overall diff size
cd /Users/carloscruz/automated-trading-platform
git show --stat

# 2. Review actual changes (first 200 lines)
git show --word-diff | head -200

# 3. Verify Python syntax
python3 -m compileall backend/app -q

# 4. Run relevant tests
cd /Users/carloscruz/automated-trading-platform/backend
python3 -m pytest tests/test_environment.py -q
```

## Red Flags 🚩

Stop and reconsider if you see:
- **Single file shows hundreds of lines changed** (e.g., `+500/-300`)
- **Large insertions/deletions in unrelated modules** (changes spill beyond the target scope)
- **Formatting-only churn** (whitespace, line wrapping without logic changes)
- **Function signatures changed** (parameters added/removed)
- **New helper methods added** when the task was "replace one check"

If you see these, the change is likely a refactor, not a small fix. Consider:
1. Splitting into multiple commits
2. Creating a separate branch for the refactor
3. Getting explicit approval for the larger change

## Example: Good Small Change

```diff
- environment = os.getenv("ENVIRONMENT", "local")
- if environment == "aws":
+ from app.core.environment import is_aws
+ if is_aws():
```

**Stats**: 2 lines changed, 1 import added. ✅

## Example: Bad "Small Change"

```diff
- def send_message(self, message: str) -> bool:
+ def send_message(self, message: str, return_meta: bool = False, record_monitoring: bool = True) -> Dict:
+     # ... 200+ lines of refactored logic ...
```

**Stats**: 200+ lines changed, signature changed, behavior changed. ❌ This is a refactor, not a small change.
