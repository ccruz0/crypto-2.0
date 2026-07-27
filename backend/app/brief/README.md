# Brief API

Server-side mail and calendar feeds for the external morning-brief agent.
Removes the dependency on Carlos’s Mac (IMAP / Outlook bridge).

Public base (via nginx): `https://dashboard.hilovivo.com/api/brief`

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/brief/mail` | Recent mail from configured IMAP mailboxes |
| `GET` | `/api/brief/calendar` | Upcoming events from published ICS URLs |

Auth (all routes): header `X-Brief-Key: <BRIEF_API_KEY>`.

Rate limit: shared sliding window (`BRIEF_RATE_LIMIT_PER_MINUTE`, default 30).

Logging / metrics never include message bodies, full email addresses, passwords, or ICS URLs.

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BRIEF_API_KEY` | yes | Shared secret for `X-Brief-Key` |
| `BRIEF_MAILBOXES_PATH` | no | Absolute path to mailboxes JSON (default `/app/secrets/brief_mailboxes.json`) |
| `BRIEF_ICS_URLS` | for calendar | Comma-separated secret ICS URLs (Outlook published calendars, Google, …) |
| `BRIEF_RATE_LIMIT_PER_MINUTE` | no | Default `30` |

Put `BRIEF_API_KEY` and `BRIEF_ICS_URLS` in `secrets/runtime.env` (never commit real values).
ICS URLs are credentials — treat them like passwords; never print them in logs or chat.

---

## Mailboxes JSON

1. Copy the example:

```bash
cp backend/app/brief/brief_mailboxes.example.json secrets/brief_mailboxes.json
chmod 600 secrets/brief_mailboxes.json
```

2. Fill `host`, `user`, and `password` for each account (credentials live in the Mac MCP `imap-*` server configs). Leave empty accounts out or incomplete — they will appear in `errors[]`.

3. Keep `hotmail-fw` label as **`Hotmail (reenviado)`** so the agent knows the real sender is inside the forwarded body (`original_from` when detected).

Adding a mailbox = edit the JSON only (no Python change). Restart / reload the backend after edits if the process caches nothing (config is read each request).

Accounts in the example: `hilovivo`, `brickeny`, `brickeny-team`, `peluqueria`, `cruzgmail`, `bumibeans`, `hotmail-fw`.

### Hotmail / Outlook.com personal

Personal Outlook.com no longer allows IMAP with a password. Use **automatic forwarding** to an IMAP mailbox (recommended: a dedicated address or folder — **not** Hilovivo’s main inbox).

Outlook.com → **Configuración → Correo → Reenvío** → enable forwarding to the IMAP destination configured as `hotmail-fw`.

---

## Calendar ICS (Outlook.com)

No Azure app registration. Publish the calendar and paste the secret ICS link into `BRIEF_ICS_URLS`.

Outlook.com → **Configuración → Calendario → Calendarios compartidos → Publicar un calendario**
→ permission **Ver todos los detalles** → copy the **ICS** link.

```bash
# secrets/runtime.env (example shape only — do not commit real URLs)
BRIEF_ICS_URLS=https://outlook.live.com/owa/calendar/SECRET/calendar.ics
# Multiple calendars:
# BRIEF_ICS_URLS=https://…/a.ics,https://calendar.google.com/calendar/ical/…/basic.ics
```

Events are expanded (including RRULE), converted to `Asia/Makassar` (UTC+8), and sorted by start.
ICS responses are cached for 30 minutes.

---

## curl (after deploy)

```bash
# Mail — last 24h
curl -sS -H "X-Brief-Key: $BRIEF_API_KEY" \
  "https://dashboard.hilovivo.com/api/brief/mail?hours=24" | jq '{window_hours, truncated, errors, counts: [.accounts[] | {id, count}]}'

# Calendar — next 2 days
curl -sS -H "X-Brief-Key: $BRIEF_API_KEY" \
  "https://dashboard.hilovivo.com/api/brief/calendar?days=2" | jq '{timezone, days, errors, n: (.events|length)}'
```

Local (backend on 8002):

```bash
curl -sS -H "X-Brief-Key: $BRIEF_API_KEY" "http://127.0.0.1:8002/api/brief/mail?hours=24"
curl -sS -H "X-Brief-Key: $BRIEF_API_KEY" "http://127.0.0.1:8002/api/brief/calendar?days=2"
```
