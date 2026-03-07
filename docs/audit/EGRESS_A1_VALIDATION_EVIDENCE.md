# Option A (A1) Egress — Validation evidence

**Instance:** i-087953603011543c5 (52.77.216.100)  
**Security group:** sg-07f5b0221b7e69efe (launch-wizard-6)  
**Region:** ap-southeast-1  
**Date:** 2026-02-20

## Egress change applied

- Removed: All traffic → 0.0.0.0/0
- Added: TCP 443, TCP 80 (169.254.169.254/32), UDP 53, TCP 53

## Validation (SSM Run Command)

- DNS + HTTPS (api.crypto.com, stream.crypto.com, api.telegram.org, api.coingecko.com): **PASS**
- Metadata: initial script used plain GET (no IMDSv2); failed on IMDSv2-only instance. Runbook updated to use IMDSv2 (token + instance-id).

## IMDSv2 metadata check — evidence

**Command:** SSM `AWS-RunShellScript` on i-087953603011543c5  
**CommandId:** 17e65329-a58c-43d8-aa24-a694b75d7964

**Output (captured):**

```
=== IMDSv2 metadata check (instance-id) ===
PASS: IMDSv2 token request (token non-empty)
PASS: IMDSv2 instance-id ok: i-087953603011543c5
=== Evidence: token flow ok, instance-id present ===
```

**Conclusion:** Token flow OK; instance-id present. Egress to metadata (TCP 80 → 169.254.169.254/32) validated. **GO** for Option A (A1).

---

*Runbook script updated in RUNBOOK_EGRESS_OPTION_A1.md to use IMDSv2 for metadata check.*
