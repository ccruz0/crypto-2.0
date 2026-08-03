# Brief API

Server-side mail, calendar, and Telegram feeds for the external morning-brief agent.
Removes the dependency on Carlos’s Mac (IMAP / Outlook / Telegram bridge).

Public base (via nginx): `https://dashboard.hilovivo.com/api/brief`

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/brief/mail` | Recent mail from configured IMAP mailboxes |
| `GET` | `/api/brief/calendar` | Upcoming events from published ICS URLs |
| `GET` | `/api/brief/telegram` | Recent incoming DMs/groups (Telethon user session) |
| `POST` | `/api/brief/send` | Send a message via the existing alert bot |

Auth (all routes): header `X-Brief-Key: <BRIEF_API_KEY>`.

Rate limit: shared sliding window (`BRIEF_RATE_LIMIT_PER_MINUTE`, default 30).

Logging / metrics never include message bodies, email addresses, passwords, ICS URLs, bot tokens, or Telethon session material.

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BRIEF_API_KEY` | yes | Shared secret for `X-Brief-Key` |
| `BRIEF_MAILBOXES_PATH` | no | Absolute path to mailboxes JSON (default `/app/secrets/brief_mailboxes.json`) |
| `BRIEF_ICS_URLS` | for calendar | Comma-separated secret ICS URLs |
| Mailbox `enabled` | no | Set `false` in `brief_mailboxes.json` to skip a stub/broken account silently |
| `BRIEF_RATE_LIMIT_PER_MINUTE` | no | Default `30` |
| `TELEGRAM_BOT_TOKEN` | for send | Existing alert bot (fallback `TELEGRAM_BOT_TOKEN_AWS`) |
| `BRIEF_TELEGRAM_CHAT_ID` | for send | Preferred destination (e.g. **Hilo vivo** channel) |
| `TELEGRAM_CHAT_ID` | for send | Fallback destination (fallback `TELEGRAM_CHAT_ID_AWS`) |
| `TELEGRAM_API_ID` | for telegram read | From https://my.telegram.org |
| `TELEGRAM_API_HASH` | for telegram read | From https://my.telegram.org |
| `TELEGRAM_SESSION_PATH` | no | Default `/data/telegram/hilovivo.session` |

Put secrets in `secrets/runtime.env` (never commit real values).
ICS URLs and the Telethon session are credentials — never print them in logs or chat.

---

## Mailboxes JSON

1. Copy the example:

```bash
cp backend/app/brief/brief_mailboxes.example.json secrets/brief_mailboxes.json
chmod 600 secrets/brief_mailboxes.json
```

2. Fill `host`, `user`, and `password` for each account. Keep `hotmail-fw` label as **`Hotmail (reenviado)`**.

Accounts in the example: `hilovivo`, `brickeny`, `brickeny-team`, `peluqueria`, `cruzgmail`, `bumibeans`, `hotmail-fw`.

Incomplete rows (empty host/user/password) and `"enabled": false` are skipped (no error). Re-enable after fixing credentials:

- **cruzgmail**: Gmail → App Password (IMAP)
- **peluqueria**: correct Hostinger mailbox password
- **hotmail-fw**: Outlook.com blocks basic IMAP auth — forward into an IMAP inbox instead
- **brickeny / bumibeans**: fill host/user/password when ready

### Agent runner

```bash
# dry-run (prints HTML brief)
python3 scripts/brief/run_morning_brief.py --dry-run

# send to BRIEF_TELEGRAM_CHAT_ID (Hilo vivo)
python3 scripts/brief/run_morning_brief.py
```

Uses `BRIEF_API_KEY` from the environment or `~/secrets/brief-agent.env`.

### Hotmail / Outlook.com personal

Use **automatic forwarding** to an IMAP mailbox (dedicated address/folder — not Hilovivo’s main inbox).

Outlook.com → **Configuración → Correo → Reenvío**.

---

## Calendar ICS (Outlook.com)

Outlook.com → **Configuración → Calendario → Calendarios compartidos → Publicar un calendario**
→ permission **Ver todos los detalles** → copy the **ICS** link into `BRIEF_ICS_URLS`.

---

## Telegram (read + send)

### Bot send (reuses existing alert credentials)

Outbound `/brief/send` reuses the existing bot token
(`TELEGRAM_BOT_TOKEN` / `TELEGRAM_BOT_TOKEN_AWS`) but should post to a dedicated chat via
`BRIEF_TELEGRAM_CHAT_ID` (e.g. the **Hilo vivo** channel). Falls back to
`TELEGRAM_CHAT_ID` / `TELEGRAM_CHAT_ID_AWS` if unset. Do **not** create a second bot token for brief.

### User-session read (Telethon)

1. Open https://my.telegram.org → **API development tools** → create an app → copy `api_id` and `api_hash`.
2. Set in `secrets/runtime.env`:

```bash
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef...
TELEGRAM_SESSION_PATH=/data/telegram/hilovivo.session
```

3. One-time interactive login (saves session on the `telegram_session_data` volume):

```bash
docker compose --profile aws exec backend-aws python scripts/telegram_login.py
```

Enter phone, login code, and 2FA if enabled. The script prints only the connected account name.

The session file equals full account access — never commit, log, or copy it off the host.

`/brief/telegram` returns private chats and groups only (broadcast channels excluded), does **not** mark messages read, and returns 409 if the session is missing/expired.

---

## curl (after deploy)

```bash
# Mail
curl -sS -H "X-Brief-Key: $BRIEF_API_KEY" \
  "https://dashboard.hilovivo.com/api/brief/mail?hours=24" | jq '{window_hours, truncated, errors, counts: [.accounts[] | {id, count}]}'

# Calendar
curl -sS -H "X-Brief-Key: $BRIEF_API_KEY" \
  "https://dashboard.hilovivo.com/api/brief/calendar?days=2" | jq '{timezone, days, errors, n: (.events|length)}'

# Telegram read
curl -sS -H "X-Brief-Key: $BRIEF_API_KEY" \
  "https://dashboard.hilovivo.com/api/brief/telegram?hours=24" | jq '{window_hours, truncated, chats: [.chats[] | {chat, chat_type, unread, n:(.messages|length)}]}'

# Telegram send
curl -sS -X POST -H "X-Brief-Key: $BRIEF_API_KEY" -H "Content-Type: application/json" \
  -d '{"text":"<b>Brief test</b>","parse_mode":"HTML"}' \
  "https://dashboard.hilovivo.com/api/brief/send"
```

Local (backend on 8002):

```bash
curl -sS -H "X-Brief-Key: $BRIEF_API_KEY" "http://127.0.0.1:8002/api/brief/telegram?hours=24"
curl -sS -X POST -H "X-Brief-Key: $BRIEF_API_KEY" -H "Content-Type: application/json" \
  -d '{"text":"Brief test"}' "http://127.0.0.1:8002/api/brief/send"
```
