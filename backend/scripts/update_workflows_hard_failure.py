#!/usr/bin/env python3
"""
Script to add HARD FAILURE CONDITION to all Watchlist/alert workflows in .cursor/workflows.json
"""
import json
import sys
import os

HARD_FAILURE_SECTION = """
6. HARD FAILURE CONDITION
   ⚠️ CRITICAL: If ANY of the following patterns are found in Monitoring entries or backend logs, the audit MUST immediately FAIL:
   - 'send_buy_signal verification'
   - 'send_sell_signal verification'
   - 'Alerta bloqueada por send_buy_signal verification'
   - 'Alerta bloqueada por send_sell_signal verification'
   - 'BLOQUEADO' (or 'BLOCKED') together with 'send_buy_signal'
   - 'BLOQUEADO' (or 'BLOCKED') together with 'send_sell_signal'
   Rule: Portfolio / business rules may block ORDERS, but must NEVER block ALERTS.
   Action on detection:
   1. Mark the audit as FAILED
   2. Stop claiming success
   3. Add a section "Blocked Alert Regression Detected" to the report
   4. List all offending messages found
   5. Start a fix loop to remove this behavior from the codebase
   6. Check telegram_notifier.py and signal_monitor.py logic
"""

HARD_FAILURE_SECTION_SIGNALMONITOR = """
HARD FAILURE CONDITION:
⚠️ CRITICAL: If ANY of the following patterns are found in Monitoring entries or backend logs, the audit MUST immediately FAIL:
- 'send_buy_signal verification'
- 'send_sell_signal verification'
- 'Alerta bloqueada por send_buy_signal verification'
- 'Alerta bloqueada por send_sell_signal verification'
- 'BLOQUEADO' (or 'BLOCKED') together with 'send_buy_signal'
- 'BLOQUEADO' (or 'BLOCKED') together with 'send_sell_signal'
Rule: Portfolio / business rules may block ORDERS, but must NEVER block ALERTS.
Action on detection:
1. Mark the audit as FAILED
2. Stop claiming success
3. Add a section "Blocked Alert Regression Detected" to the report
4. List all offending messages found
5. Start a fix loop to remove this behavior from the codebase
6. Check telegram_notifier.py and signal_monitor.py logic
"""

REPORT_ADDITION = """
- Blocked Alert Regression section (if any patterns detected):
  - List all offending messages
  - Root cause analysis
  - Fixes applied
- Explicit confirmation that NO blocked alert patterns were found
"""

def update_workflow_prompt(prompt, workflow_name):
    """Add HARD FAILURE CONDITION to workflow prompt"""
    
    # Check if already updated
    if "HARD FAILURE CONDITION" in prompt:
        return prompt
    
    # For Strict Watchlist Audit
    if "Strict Watchlist Audit" in workflow_name:
        # Add after "5. Special Focus Symbols"
        if "5. Special Focus Symbols" in prompt:
            prompt = prompt.replace(
                "5. Special Focus Symbols",
                "5. Special Focus Symbols" + HARD_FAILURE_SECTION
            )
        # Update OUTPUT section
        if "Final statement:" in prompt:
            prompt = prompt.replace(
                "- Note any technical debt or TODOs that remain.",
                "- Note any technical debt or TODOs that remain." + REPORT_ADDITION
            )
    
    # For Strict Watchlist Runtime Audit
    elif "Strict Watchlist Runtime Audit" in workflow_name:
        # Add after "4. Alert generation"
        if "4. Alert generation (CRITICAL):" in prompt:
            # Find the end of section 4 and add section 5
            prompt = prompt.replace(
                "   This MUST be validated for:\n   - ALGO\n   - LDO\n   - TON\n\n5. VALIDATE IN BROWSER:",
                "   This MUST be validated for:\n   - ALGO\n   - LDO\n   - TON\n\n" + HARD_FAILURE_SECTION + "\n\n6. VALIDATE IN BROWSER:"
            )
        # Update FINAL OUTPUT
        if "Include:" in prompt and "Confirmation of alert emission" in prompt:
            prompt = prompt.replace(
                "- Confirmation of alert emission",
                "- Confirmation of alert emission" + REPORT_ADDITION
            )
    
    # For SignalMonitor Deep Audit
    elif "SignalMonitor Deep Audit" in workflow_name:
        # Add after HARD REQUIREMENT
        if "HARD REQUIREMENT:" in prompt and "If the Watchlist shows BUY but NO alert is sent" in prompt:
            prompt = prompt.replace(
                "If the Watchlist shows BUY but NO alert is sent, this is a CRITICAL FAILURE. Diagnose and fix.\n\n",
                "If the Watchlist shows BUY but NO alert is sent, this is a CRITICAL FAILURE. Diagnose and fix.\n\n" + HARD_FAILURE_SECTION_SIGNALMONITOR + "\n\n"
            )
        # Update FINAL OUTPUT
        if "Include:" in prompt and "Final validation results" in prompt:
            prompt = prompt.replace(
                "- Final validation results",
                "- Final validation results" + REPORT_ADDITION
            )
    
    return prompt

def main():
    workflows_file = ".cursor/workflows.json"
    
    if not os.path.exists(workflows_file):
        print(f"Error: {workflows_file} not found")
        sys.exit(1)
    
    with open(workflows_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    updated = False
    for workflow in data.get("workflows", []):
        if any(keyword in workflow.get("name", "") for keyword in [
            "Strict Watchlist Audit",
            "Strict Watchlist Runtime Audit",
            "SignalMonitor Deep Audit"
        ]):
            old_prompt = workflow["prompt"]
            new_prompt = update_workflow_prompt(old_prompt, workflow["name"])
            if new_prompt != old_prompt:
                workflow["prompt"] = new_prompt
                updated = True
                print(f"Updated: {workflow['name']}")
    
    if updated:
        with open(workflows_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"✅ Updated {workflows_file}")
    else:
        print("No updates needed")

if __name__ == "__main__":
    main()






