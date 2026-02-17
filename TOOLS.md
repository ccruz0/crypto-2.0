# TOOLS.md

Local notes: tools, credentials hints, preferences. Do not store secrets in plain text.

---

## EC2 Read-Only Runner Contract (Claw)

When proposing commands for EC2 diagnostics:

- **You must output exactly one command line.**
- It must be compatible with `./ops/clawctl/clawctl.sh "<cmd>"`
- It must start with an allowlisted verb (`ps`, `pstree`, `journalctl`, `docker logs`, etc.).
- No sudo, no restarts, no writes.
- Prefer 1–3 commands max per step.

**Response format:**

```
EC2_CMD: <one-liner here>
WHY: <one sentence>
NEXT: <what output you need next>
```

**Workflow:** User asks for read-only diagnostics → copy `EC2_CMD:` line → run via `clawctl.sh` → paste output back. No ambiguity.
