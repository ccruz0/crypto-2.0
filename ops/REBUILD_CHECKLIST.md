# Post-compromise rebuild checklist

## PHASE A — Inventory
- [x] DONE: Scan repo for required env vars
- [x] DONE: Create `ops/atp.env.template`
- [x] DONE: Create `ops/print_required_env.sh` and `ops/inventory_env_vars.sh`
- [x] DONE: Create `ops/generate_secrets.sh`

## PHASE B — Interactive secret rotation (one by one)
- [x] DONE: POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB (keep atp, trader)
- [ ] WAITING: DATABASE_URL (set after password is in atp.env)
- [ ] WAITING: SECRET_KEY
- [x] DONE: DIAGNOSTICS_API_KEY
- [ ] WAITING: ADMIN_ACTIONS_KEY (valor generado; guardar en EC2)
- [ ] WAITING: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (and _AWS, _ALERT)
- [ ] WAITING: EXCHANGE_CUSTOM_API_KEY / EXCHANGE_CUSTOM_API_SECRET
- [ ] WAITING: GRAFANA (GRAFANA_ADMIN_USER / GF_SECURITY_ADMIN_PASSWORD)
- [ ] WAITING: FRONTEND_URL / AWS_INSTANCE_IP (non-secret)

## PHASE C — Deploy on new EC2
- [ ] WAITING: Create /opt/atp and /opt/atp/atp.env (ubuntu, 600)
- [ ] WAITING: Docker + Compose on EC2
- [ ] WAITING: docker compose --profile aws --env-file /opt/atp/atp.env up -d --build
- [ ] WAITING: Validations (ps, no docker.sock, diagnostics 404 without key)

## PHASE D — Post-deploy hardening
- [ ] WAITING: AWS SSM / close SSH
- [ ] WAITING: Egress restriction (UFW / SG)
- [ ] WAITING: Logs/alerts verified
