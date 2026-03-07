# Runbook: Exchange credentials modal and EC2 verification

The dashboard modal **Set Exchange Credentials** writes `EXCHANGE_CUSTOM_API_KEY` and `EXCHANGE_CUSTOM_API_SECRET` into `secrets/runtime.env`. Backend must be restarted for them to take effect. This runbook verifies the flow on EC2 and avoids the “file not writable” trap.

---

## 1. Confirm the file is writable inside the container

On EC2:

```bash
cd /home/ubuntu/automated-trading-platform

docker exec automated-trading-platform-backend-aws-1 sh -lc '
ls -la /app/secrets/runtime.env
id
'
```

- If you see **No such file or directory**: the backend is not running with the `runtime.env` volume mount. Pull latest (compose with `./secrets/runtime.env:/app/secrets/runtime.env` under `backend-aws` volumes) and recreate:  
  `sudo docker compose --profile aws up -d --force-recreate backend-aws`
- If the file exists but is **owned by root** (e.g. `root root`), the container user (e.g. `uid=10001(appuser)`) cannot write. Fix once on the host:

```bash
sudo chown 10001:10001 secrets/runtime.env
sudo chmod 600 secrets/runtime.env
sudo docker compose --profile aws up -d --force-recreate backend-aws
```

(Use `10001` only if your backend container runs as that UID; confirm with `id` inside the container.)

---

## 2. After saving via modal – check the host file

```bash
sudo grep -nE '^EXCHANGE_CUSTOM_API_(KEY|SECRET)=' secrets/runtime.env | sed 's/=.*/=***/'
```

You must see both lines (e.g. `EXCHANGE_CUSTOM_API_KEY=***` and `EXCHANGE_CUSTOM_API_SECRET=***`). If not, the modal did not persist (e.g. permission denied; re-check step 1).

**Alternative – add credentials directly on EC2:** SSH to the instance, then run `bash scripts/ec2_add_exchange_credentials.sh` (from the repo). It prompts for API Key and Secret, appends them to `secrets/runtime.env`, fixes perms; then restart the backend.

---

## 3. After restart – confirm keys are in environment

```bash
docker exec automated-trading-platform-backend-aws-1 sh -lc '
for k in EXCHANGE_CUSTOM_API_KEY EXCHANGE_CUSTOM_API_SECRET; do
  [ -n "$(printenv "$k")" ] && echo "$k=SET" || echo "$k=MISSING"
done
'
```

Both must be **SET**.

---

## 4. Verify dashboard API

```bash
curl -sS http://127.0.0.1:8002/api/dashboard/state | head -c 1500 && echo
```

Expect:

- `"source"` not `"error"`
- `"portfolio_last_updated"` not null
- Non-empty `"balances"` or `"portfolio"."assets"`

---

## Security note

- When **ADMIN_ACTIONS_KEY** is set, `POST /api/settings/exchange-credentials` requires the **X-Admin-Key** header. Use the optional “Admin key” field in the modal (same value as `ADMIN_ACTIONS_KEY`).
- If `ADMIN_ACTIONS_KEY` is not set, the endpoint is unprotected (dev-only). For production, set `ADMIN_ACTIONS_KEY` in `secrets/runtime.env` and use the admin key in the modal when saving.

---

## Crypto.com IP whitelist

The exchange sees your **public outbound IP**, not a private 172.x address. Whitelist that IP in Crypto.com API settings.

**Get the IP (on EC2):** `curl -s https://checkip.amazonaws.com`

**Optional – from inside the backend container:**  
`docker exec automated-trading-platform-backend-aws-1 sh -lc 'curl -s https://checkip.amazonaws.com'`

Whitelist the returned IP in Crypto.com. If the instance has no Elastic IP, the public IP can change on stop/start; allocate and attach an Elastic IP, then whitelist that IP for stability.
