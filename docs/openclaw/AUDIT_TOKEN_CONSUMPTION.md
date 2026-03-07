# Audit: How OpenClaw Consumes the GitHub Token

**Scope:** This repo (automated-trading-platform / crypto-2.0). The **OpenClaw application** (code inside the container image `ghcr.io/ccruz0/openclaw`) is **not** in this repo; that image’s source must be audited separately.

---

## 1. What This Repo Controls

| Item | Location | Finding |
|------|----------|--------|
| **Token passed to container** | `docker-compose.openclaw.yml` | Only **path** is passed: `OPENCLAW_TOKEN_FILE=/run/secrets/openclaw_token`. Token bytes are **not** in env. |
| **Token on host** | Compose volume | `/home/ubuntu/secrets/openclaw_token` mounted **read-only** as `/run/secrets/openclaw_token:ro`. |
| **git clone in this repo** | `install_on_lab.sh`, `install_on_lab_prep.sh`, `print_lab_commands.sh`, `prompt_pat_and_install.sh` | All use `git clone "$GIT_REPO_URL"` or `https://github.com/ccruz0/crypto-2.0.git` — **no** `https://token@github.com/...`. ✅ |
| **credential.helper / git config** | Docs only | `LAB_SETUP_AND_VALIDATION.md` documents a **credential helper** that reads from the token file and outputs `password=...` to stdout (for Git only). No credential helper or git config in **scripts** that would write the token to URL or store. |

---

## 2. Search Results (this repo)

| Pattern | Files / lines | Notes |
|---------|----------------|-------|
| **OPENCLAW_TOKEN_FILE** | `docker-compose.openclaw.yml:22` | Env var set to path only. ✅ |
| **GITHUB_TOKEN** | `backend/app/api/routes_monitoring.py:2515` | Used for **dashboard_data_integrity** workflow trigger (backend, not OpenClaw). Unrelated to OpenClaw container. |
| **GH_TOKEN** | Not found | — |
| **credential.helper** | `docs/openclaw/LAB_SETUP_AND_VALIDATION.md` (doc) | Doc only; helper reads from file, outputs to stdout for Git. |
| **git config** (token-related) | Deploy scripts set `safe.directory` only; no credential store. | ✅ |
| **os.getenv** (token) | `routes_monitoring.py` (GITHUB_TOKEN for workflow dispatch) | Not OpenClaw. |
| **print(token)** / **logging token** | Various Telegram/Crypto scripts; none for OpenClaw token. | No OpenClaw token printed or logged in this repo. |
| **Logging of headers** | `http_client.py` redacts Telegram token in logs. | No OpenClaw token in HTTP logging in this repo. |

---

## 3. Verification Checklist (this repo)

| # | Requirement | Status |
|---|-------------|--------|
| 1 | Token read only from file path in OPENCLAW_TOKEN_FILE | **Container env** only exposes path. Actual read is done **inside the OpenClaw image** — not auditable here. |
| 2 | No fallback to environment variables | **This repo** does not set any GITHUB_TOKEN/GH_TOKEN for the OpenClaw service. Compose only sets OPENCLAW_TOKEN_FILE. ✅ |
| 3 | Token is not logged | No script or app in this repo logs the OpenClaw token. ✅ |
| 4 | Token is not written to workspace | No script writes the token into the repo or workspace. ✅ |
| 5 | Token not passed to git clone as `https://token@...` | All clone invocations use plain URL. ✅ |

---

## 4. Documentation Risks (minimal)

- **LAB_SETUP_AND_VALIDATION.md** and **FINAL_SECURITY_CHECKLIST.md** show validation commands that do `TOKEN=$(cat ~/secrets/openclaw_token)` and `export TOKEN=...` and `Authorization: Bearer $TOKEN`. Intended for **manual** runs; if run from a script that logs commands or stdout, the token could leak. Recommendation: add a short warning in those sections.
- **FINAL_SECURITY_CHECKLIST.md** (around “.env.lab”) still refers to `OPENCLAW_TOKEN_PATH` in .env; we now use a **hardcoded path** in compose. Recommendation: update the checklist to match.

---

## 5. OpenClaw Container (image) — Out of Scope Here

The application that runs **inside** the OpenClaw container (image `ghcr.io/ccruz0/openclaw`) is **not** in this repository. To fully satisfy the audit, that application’s source (wherever it lives) should be checked for:

1. **Token read only from file:** Use only `OPENCLAW_TOKEN_FILE`; read contents from that path; no reading from env.
2. **No fallback:** Do not use `GITHUB_TOKEN`, `GH_TOKEN`, or any other env var as fallback.
3. **No logging:** Never log the token or the file contents; never log `Authorization` header value.
4. **No write to workspace:** Do not write the token (or the file) into the repo workspace or any world-readable path.
5. **No git URL with token:** Do not construct `https://<token>@github.com/...` for clone/fetch; use Git credential helper or API with token in header only.

---

## 6. Summary

- **This repo:** Token is only passed as a **file path** and a **read-only mount**; no token in env, no token in git clone URLs, no logging of the token. Documentation has minor clarifications recommended.
- **OpenClaw image:** Must be audited in its **own** source repo for the five points in §5.

**Next steps (no code change in this repo):**
- **On LAB:** Run the checks in [VERIFY_OPENCLAW_CONTAINER.md](VERIFY_OPENCLAW_CONTAINER.md) (env, logs, optional grep inside container).
- **If you have the OpenClaw source repo:** Use the prompt in [PROMPT_AUDIT_OPENCLAW_SOURCE.md](PROMPT_AUDIT_OPENCLAW_SOURCE.md) in Cursor there to get a report + minimal patch.
