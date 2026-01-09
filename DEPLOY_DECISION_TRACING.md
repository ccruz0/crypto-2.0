# Decision Tracing Deployment Instructions

## ✅ Commits Pushed

**Backend:** `5ebec6c` - feat: Implement decision tracing for buy order attempts
**Frontend:** `2b031db` - feat: Add decision tracing fields to Monitor UI

## 📋 Deployment Steps

### Step 1: Run Database Migration

The database migration must be run manually on the AWS server before the backend starts using the new fields.

**Option A: Via SSH (if direct SSH access)**
```bash
ssh hilovivo-aws  # or your AWS connection
cd ~/automated-trading-platform
psql -U trader -d atp -f backend/migrations/add_decision_tracing_fields.sql
```

**Option B: Via Docker Compose (if using Docker)**
```bash
ssh hilovivo-aws
cd ~/automated-trading-platform
docker compose --profile aws exec -T db psql -U trader -d atp -f /path/to/add_decision_tracing_fields.sql
# Or copy the file first:
docker compose --profile aws cp backend/migrations/add_decision_tracing_fields.sql db:/tmp/
docker compose --profile aws exec -T db psql -U trader -d atp -f /tmp/add_decision_tracing_fields.sql
```

**Option C: Via Python Script (if using SQLAlchemy)**
```bash
# Create a script to run the migration
python3 -c "
from app.database import engine
with open('backend/migrations/add_decision_tracing_fields.sql', 'r') as f:
    sql = f.read()
with engine.connect() as conn:
    conn.execute(text(sql))
    conn.commit()
"
```

### Step 2: Verify Migration

After running the migration, verify the new columns exist:

```sql
SELECT 
    column_name, 
    data_type, 
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'telegram_messages' 
AND column_name IN ('decision_type', 'reason_code', 'reason_message', 'context_json', 'exchange_error_snippet', 'correlation_id')
ORDER BY column_name;
```

Expected output: 6 rows (one for each new column)

### Step 3: Deploy Backend Code

The GitHub Actions workflow should automatically deploy on push to main. If not:

**Via GitHub Actions:**
- Check workflow status: https://github.com/ccruz0/crypto-2.0/actions
- If failed, re-run the workflow

**Manual deployment:**
```bash
# Use your deployment script
./scripts/deploy_aws_backend.sh
# or
./deploy_backend_full.sh
```

### Step 4: Deploy Frontend Code

Frontend deployment is automatic via GitHub Actions if frontend is a submodule.

If manual deployment needed:
```bash
# Frontend is a separate repo, so it should auto-deploy if CI/CD is configured
# Or manually:
cd frontend
git pull origin main
npm install
npm run build
# Then deploy to your hosting
```

### Step 5: Restart Services (if needed)

After code deployment and migration:

```bash
ssh hilovivo-aws
cd ~/automated-trading-platform
docker compose --profile aws restart backend-aws
# Or if not using Docker:
# pkill -f "uvicorn app.main:app" && nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
```

### Step 6: Verify Deployment

1. **Check backend logs:**
   ```bash
   docker compose --profile aws logs -n 100 backend-aws | grep -i "decision\|reason\|DECISION"
   ```

2. **Test the API endpoint:**
   ```bash
   curl http://your-aws-host:8000/api/monitoring/telegram-messages | jq '.messages[0] | {decision_type, reason_code, reason_message}'
   ```

3. **Check Monitor UI:**
   - Navigate to Monitor tab
   - Open "Telegram (Mensajes Bloqueados)" section
   - Verify blocked messages show:
     - Decision type badge (SKIPPED/FAILED)
     - Reason code
     - Reason message
     - Expandable "Details" button

## 🔍 Testing Checklist

After deployment, test these scenarios:

- [ ] Trade disabled → Should see SKIPPED with TRADE_DISABLED
- [ ] Invalid trade amount → Should see SKIPPED with INVALID_TRADE_AMOUNT
- [ ] Insufficient balance → Should see SKIPPED with INSUFFICIENT_AVAILABLE_BALANCE
- [ ] Max open orders → Should see SKIPPED with MAX_OPEN_TRADES_REACHED
- [ ] Cooldown active → Should see SKIPPED with COOLDOWN_ACTIVE or THROTTLED_DUPLICATE_ALERT
- [ ] Exchange failure → Should see FAILED with appropriate reason code + Telegram notification
- [ ] Monitor UI shows all fields correctly
- [ ] Expandable details work correctly
- [ ] Correlation IDs are generated and displayed

## ⚠️ Important Notes

1. **Database Migration is Required:** The new fields won't work until the migration is run
2. **Backward Compatible:** Existing rows will have NULL for new fields until populated
3. **No Manual Refresh Needed:** Monitor UI uses existing polling mechanism
4. **Telegram Notifications:** FAILED decisions automatically send Telegram failure notifications with reason details

## 🐛 Troubleshooting

**If migration fails:**
- Check PostgreSQL connection: `psql -U trader -d atp -c "SELECT 1;"`
- Verify file path: `ls -la backend/migrations/add_decision_tracing_fields.sql`
- Check permissions: Ensure trader user can ALTER TABLE telegram_messages

**If backend fails to start:**
- Check logs: `docker compose --profile aws logs backend-aws`
- Verify imports: `python3 -c "from app.utils.decision_reason import DecisionReason"`
- Check database connection

**If UI doesn't show fields:**
- Clear browser cache
- Check browser console for errors
- Verify API returns new fields: `curl http://your-host/api/monitoring/telegram-messages | jq '.messages[0]'`
- Check frontend build succeeded

