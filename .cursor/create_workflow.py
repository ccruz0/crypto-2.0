#!/usr/bin/env python3
"""
Script to create Cursor workflow programmatically.
This attempts to add the workflow to Cursor's configuration.
"""

import json
import os
import sys
from pathlib import Path

WORKFLOW_CONFIG = {
    "name": "Strict Watchlist Audit",
    "triggerKeywords": [
        "audit watchlist",
        "watchlist audit",
        "strict audit",
        "verify watchlist",
        "check signals"
    ],
    "autoTrigger": True,
    "prompt": """You act as an autonomous agent running a FULL STRICT AUDIT of the Watchlist tab
for the "automated-trading-platform" project.

Never ask the user questions.
Never wait for confirmation.
Run the full autonomous cycle:

  INVESTIGATE → REASON → FIX → IMPLEMENT → TEST → DEPLOY → OPEN LIVE DASHBOARD → VALIDATE → ITERATE

Continue until EVERYTHING in the Watchlist behaves according to the Business Rules.

==================================================
CONTEXT
==================================================

Project root (local):
  /Users/carloscruz/automated-trading-platform

Remote host (SSH config already set up):
  hilovivo-aws

Remote project path:
  /home/ubuntu/automated-trading-platform

ALWAYS run remote shell commands via:
  sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && ...'"

Key documentation files (source of truth):

- docs/monitoring/business_rules_canonical.md
- docs/monitoring/signal_flow_overview.md
- docs/WORKFLOW_WATCHLIST_AUDIT.md
- docs/CURSOR_AUTONOMOUS_EXECUTION_GUIDELINES.md

You MUST read and follow those documents before making any changes.

Constraints:
- You ARE allowed to generate alerts.
- You are NOT allowed to create real trading orders on the exchange.
- You MUST test backend + frontend + AWS deployment + live browser behavior.
- You MUST keep iterating until there are ZERO mismatches between frontend and backend behavior.

==================================================
WATCHLIST AUDIT TASK
==================================================

Your job is to perform a STRICT end-to-end audit of the Watchlist tab:

1. Backend vs Business Rules
   - Read business_rules_canonical.md and signal_flow_overview.md.
   - Validate that backend BUY/SELL decision logic strictly follows those rules.
   - Canonical rule:
       If ALL boolean buy_* flags are TRUE:
         → strategy.decision MUST be "BUY"
         → buy_signal MUST be true.

2. Backend vs Frontend (UI)
   - For each coin in the watchlist:
     - Ensure frontend Signals chip EXACTLY matches backend strategy_state.decision.
     - Ensure frontend Index chip EXACTLY matches backend strategy_state.index.
     - Ensure displayed RSI, MA, EMA, Volume ratio match backend numeric values.

3. Toggles & Persistence
   - Check that "Trading" (Trade = YES/NO) toggle persists correctly in DB
     and is read by the monitor from the same canonical record.
   - Check that "Alerts" toggle persists correctly and is respected by the monitor.
   - Verify that when Trading is NO but Alerts ON:
     - NO real orders are created.
     - Alerts are STILL evaluated and sent according to rules.

4. Alert Generation
   - For every symbol where:
       - strategy.decision = "BUY"
       - alert_enabled = true
       - throttle conditions are satisfied
     → A BUY alert MUST be sent (no silent skips).
   - Verify alerts appear in:
       - Monitoring → Telegram Messages tab
       - Telegram test channel (if configured in the project).

5. Special Focus Symbols
   - Explicitly validate ALGO, LDO, TON:
     - Ensure they follow the same logic as the rest.
     - Ensure no hard-coded exceptions exist.
     - Ensure alerts fire correctly when all criteria are met.

==================================================
AUTONOMOUS FIX LOOP
==================================================

For ANY mismatch you detect (logic, data, UI, persistence, or alerts):

1. IDENTIFY root cause.
2. DESIGN a fix (backend and/or frontend).
3. IMPLEMENT the fix in the repo:
   - Update TypeScript/React code for the frontend where needed.
   - Update Python/FastAPI/services code for the backend where needed.
4. RUN TESTS:
   - Frontend: npm/yarn lint and build.
   - Backend: pytest or the existing test suite.
5. DEPLOY TO AWS:
   - Rebuild and restart the appropriate Docker services using the remote path and SSH command pattern.
6. VALIDATE LIVE:
   - Open the production dashboard in a browser.
   - Go to the Watchlist tab.
   - Verify behavior matches Business Rules.
   - Check browser console and network calls.
   - Check backend logs for DEBUG_STRATEGY_* markers and alert emits.
7. ITERATE:
   - If something is still wrong, repeat the loop until all issues are resolved.

You MUST NOT stop after the first apparent fix.
You MUST keep iterating until:
- No symbol violates the canonical BUY rule.
- No mismatch exists between backend decision and frontend display.
- Alerts are sent whenever Business Rules say they must be sent.
- Toggles persist and behave exactly as defined.

==================================================
OUTPUT & REPORT
==================================================

At the end of the audit and fix loop, create or update:

  docs/WORKFLOW_WATCHLIST_STRICT_AUDIT_REPORT.md

The report MUST include:

- A list of all mismatches found (before fixes), grouped by:
  - Logic issues
  - Persistence issues
  - UI mismatches
  - Alert emission issues
- For each issue:
  - Root cause (file, function, line range).
  - Fix applied (high-level explanation + code diff summary).
- Evidence of validation:
  - References to backend logs (e.g. DEBUG_STRATEGY_FINAL entries).
  - Screenshots or description of frontend Watchlist behavior after the fix.
- Final statement:
  - Explicit confirmation that ALL Business Rules are satisfied.
  - Note any technical debt or TODOs that remain.

Once the report is written and saved in the repo,
consider the workflow run COMPLETE.

END OF WORKFLOW PROMPT."""
}

def main():
    """Create workflow configuration file."""
    workspace_root = Path("/Users/carloscruz/automated-trading-platform")
    cursor_dir = workspace_root / ".cursor"
    cursor_dir.mkdir(exist_ok=True)
    
    workflow_file = cursor_dir / "workflows.json"
    
    # Read existing workflows if any
    workflows = {"workflows": []}
    if workflow_file.exists():
        try:
            with open(workflow_file, 'r') as f:
                workflows = json.load(f)
        except:
            pass
    
    # Check if workflow already exists
    existing_names = [w.get("name", "") for w in workflows.get("workflows", [])]
    if "Strict Watchlist Audit" in existing_names:
        # Update existing workflow
        for i, wf in enumerate(workflows.get("workflows", [])):
            if wf.get("name") == "Strict Watchlist Audit":
                workflows["workflows"][i] = WORKFLOW_CONFIG
                break
    else:
        # Add new workflow
        if "workflows" not in workflows:
            workflows["workflows"] = []
        workflows["workflows"].append(WORKFLOW_CONFIG)
    
    # Write back
    with open(workflow_file, 'w') as f:
        json.dump(workflows, f, indent=2)
    
    print(f"✓ Workflow configuration saved to {workflow_file}")
    print(f"  Name: {WORKFLOW_CONFIG['name']}")
    print(f"  Trigger Keywords: {', '.join(WORKFLOW_CONFIG['triggerKeywords'])}")
    print(f"  Auto-trigger: {WORKFLOW_CONFIG['autoTrigger']}")
    print("\n⚠️  Note: You may need to manually import this workflow in Cursor Settings → Workflows")
    print("   or restart Cursor for it to be recognized.")

if __name__ == "__main__":
    main()






