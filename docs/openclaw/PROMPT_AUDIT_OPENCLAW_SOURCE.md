# Prompt para Cursor: auditar consumo del token en el repo OpenClaw

Abre en Cursor el **repo donde se construye** `ghcr.io/ccruz0/openclaw:latest` y pega el siguiente bloque completo.

---

```
Audit OpenClaw token consumption (security-critical).

Goal:
Ensure OpenClaw reads the GitHub token ONLY from the file path in OPENCLAW_TOKEN_FILE and never from env vars like GITHUB_TOKEN/GH_TOKEN, never logs it, never writes it to disk, and never embeds it in git URLs.

Tasks:
1) Locate token-loading code:
   - Search for: OPENCLAW_TOKEN_FILE, openclaw_token, /run/secrets, GITHUB_TOKEN, GH_TOKEN, Authorization, Bearer, requests headers.
   - Identify the exact function/class that loads credentials.

2) Enforce strict rules:
   - Token source must be ONLY: read(openclaw_token_file).strip()
   - If OPENCLAW_TOKEN_FILE is missing/unreadable -> hard fail with a safe error (no token content).
   - No fallback to GITHUB_TOKEN/GH_TOKEN or any other env var.

3) Prevent leaks:
   - Ensure logs never print token, headers, or full request objects.
   - Redact Authorization header if any request logging exists.
   - Ensure exceptions never include token content.

4) Git usage:
   - Ensure git clone/fetch never uses https://<token>@github.com URLs.
   - Prefer credential helper via file or use API headers, but never embed token in URL.

Deliverables:
- A short report with file paths + line numbers for all relevant code.
- A minimal patch implementing:
  - strict token source = file only
  - redaction for any logging
  - tests that assert token is not read from env and not printed

Constraints:
- Minimal changes.
- Do not refactor unrelated code.
```

---

Después de ejecutar, revisa el informe y los parches antes de aplicarlos.
