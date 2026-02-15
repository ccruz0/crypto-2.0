# OpenClaw audit prompt (paste into OpenClaw)

Use this when starting OpenClaw inside the agent container for an audit-only run.

---

HIGH-SECURITY MODE.

Network:
- You can reach ONLY https://api.openai.com via the configured proxy.
- No other outbound access must be attempted.
- No npm install. Dependencies already present. Do not attempt downloads.

Secrets:
- Read the OpenAI key only from OPENAI_API_KEY_FILE.
- Never print secrets. Never write secrets to disk.

Scope:
- Read/modify only backend/, docs/, tests/, security/openclaw/
- For this run: AUDIT ONLY. Do not change any code.

Deliverables:
- docs/openclaw/AUDIT_REPORT.md
- docs/openclaw/RISK_REGISTER.md
- docs/openclaw/TEST_GAPS.md

Stop after writing those files.
