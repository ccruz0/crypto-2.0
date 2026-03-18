# Fix: DB "password authentication failed for user trader"

**Symptom:** `/api/health/system` returns `db_status: "down"` and all components (Market, Updater, etc.) show FAIL. Backend or market-updater logs show: `FATAL: password authentication failed for user "trader"`.

**Cause:** The password in `DATABASE_URL` (used by backend-aws and market-updater-aws) does not match the password the Postgres container is using for user `trader`.

**Note:** The market updater container may still be *running* and fetching prices; it will fail when writing to the DB, and the health check fails because the backend cannot connect to the DB.

---

## Fix (pick one approach)

### Option A: Align env files (recommended)

1. **Which file wins for each service** (later file overrides earlier):
   - **db:** `env_file: .env` → `.env.local` → `.env.aws`  
     So `POSTGRES_PASSWORD` is taken from whichever of these sets it last (typically `.env` or `.env.aws`).
   - **backend-aws & market-updater-aws:** `env_file: .env` → `.env.aws` → `./secrets/runtime.env`  
     So `DATABASE_URL` is taken from whichever of these sets it last (often `secrets/runtime.env`).

2. **Ensure they match**  
   - Pick one password value.
   - Set **POSTGRES_PASSWORD** in the file the `db` service actually uses (e.g. `.env` or `.env.aws`). If the DB volume was created earlier, the password in Postgres is already set; then set **DATABASE_URL** to use that same password.
   - Set **DATABASE_URL=postgresql://trader:<same_password>@db:5432/atp** in the file that backend-aws and market-updater-aws use (often `secrets/runtime.env`). The password inside `DATABASE_URL` must match `POSTGRES_PASSWORD` exactly.

3. **Restart services** (no need to recreate the DB volume):
   ```bash
   cd /path/to/automated-trading-platform
   docker compose --profile aws restart backend-aws market-updater-aws
   ```
   Wait ~30s, then:
   ```bash
   curl -sS http://127.0.0.1:8002/api/health/system | jq '.db_status, .market_data.status, .market_updater.status'
   ```
   Expect: `db_status` "up", then market_data and market_updater can show PASS once data is fresh.

### Option B: Change the DB password to match DATABASE_URL

If you want to keep `DATABASE_URL` as-is and change Postgres to accept that password:

1. Connect to Postgres as a superuser (e.g. from host or a temporary container that has the current password).
2. Run:
   ```sql
   ALTER USER trader WITH PASSWORD 'the_password_from_your_DATABASE_URL';
   ```
3. Restart backend and market-updater (as in Option A step 3).

### Option C: DB was first created with a different password

If the `db` volume was initialized earlier with a different `POSTGRES_PASSWORD`, Postgres keeps that password. Either:

- Set `DATABASE_URL` (in backend/market-updater env) to use that **existing** password, or  
- Reset the DB (only if you can lose existing data): remove the `postgres_data` volume, set `POSTGRES_PASSWORD` and `DATABASE_URL` to the same value, then `docker compose --profile aws up -d` and run migrations again.

---

## Verify

After editing env and restarting:

```bash
cd /path/to/automated-trading-platform
docker compose --profile aws restart backend-aws market-updater-aws
sleep 35
curl -sS http://127.0.0.1:8002/api/health/system | jq '.db_status, .market_data.status, .market_updater.status'
```

Or run the script (no secrets printed):

```bash
./scripts/diag/verify_db_password_match.sh
```

Expect: `db_status` "up"; then after the next market updater cycle (~60s), `market_data.status` and `market_updater.status` can be PASS.
