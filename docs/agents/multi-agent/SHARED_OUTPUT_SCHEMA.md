# Shared Agent Output Schema

All multi-agent operator responses MUST follow this structure. OpenClaw is instructed to produce markdown with exactly these section headings.

---

## Schema

| Section | Purpose |
|---------|---------|
| **Issue Summary** | One-paragraph description of the issue and impact |
| **Scope Reviewed** | Files, modules, docs, and endpoints the agent examined |
| **Confirmed Facts** | What was verified from code/config/logs (no speculation) |
| **Mismatches** | Code vs docs, expected vs actual, inconsistencies |
| **Root Cause** | Most likely cause; cite evidence |
| **Proposed Minimal Fix** | Smallest safe change; concrete steps or code snippets |
| **Risk Level** | LOW / MEDIUM / HIGH; brief justification |
| **Validation Plan** | How to verify the fix; commands, checks, rollback |
| **Cursor Patch Prompt** | Copy-paste prompt for Cursor to apply the fix |

---

## Markdown format

```markdown
## Issue Summary
...

## Scope Reviewed
...

## Confirmed Facts
...

## Mismatches
...

## Root Cause
...

## Proposed Minimal Fix
...

## Risk Level
LOW | MEDIUM | HIGH
...

## Validation Plan
...

## Cursor Patch Prompt
...
```

If a section is not applicable, include the heading and write `N/A`.

---

## Validation checklist (per agent)

- [ ] All 9 sections present (mandatory; validator rejects if any missing)
- [ ] Root Cause, Proposed Minimal Fix, Risk Level, Cursor Patch Prompt have meaningful content (≥15 chars; N/A only when truly not applicable)
- [ ] Risk Level contains LOW, MEDIUM, or HIGH
- [ ] No invented facts; "Confirmed Facts" cites real code/config
- [ ] "Proposed Minimal Fix" is actionable (file paths, exact changes)
- [ ] "Cursor Patch Prompt" is self-contained and copy-pasteable
- [ ] Minimum body length: 500 chars (agent output)

## Validation failures (actionable messages)

| Failure | Message | Action |
|---------|---------|--------|
| Missing sections | "Agent output missing required sections: X, Y. Add each as '## X' with content or N/A." | Add missing headings and content |
| Content too short | "Output too short (N chars, minimum 500). Expand each section with concrete findings." | Expand sections |
| Critical sections weak | "Critical sections need more content: Root Cause, Proposed Minimal Fix. Each must have concrete findings." | Add concrete findings |
